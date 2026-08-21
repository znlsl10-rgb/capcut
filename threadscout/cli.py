"""threadscout CLI.

사용 예:
    # 1) 해외 스레드에서 '노출 잘 되고 댓글/공유 많은' 글 찾기 + 쿠팡 매칭 + 한국어 초안
    export APIFY_TOKEN=apify_api_...
    python -m threadscout scan --keyword "air fryer" --keyword "amazon finds" \
        --max-posts 80 --days 30 --top 20 --save-raw output/raw.json

    # 2) 저장해둔 원시 데이터로 재분석 (Apify 비용 0)
    python -m threadscout scan --from-json output/raw.json --top 30

    # 3) 쿠팡에 파는 물건인지만 확인 (+파트너스 키 있으면 제휴 링크까지)
    python -m threadscout coupang "에어프라이어" "무선청소기"

    # 4) 쿠팡 상품 URL → 내 파트너스 딥링크
    python -m threadscout link https://www.coupang.com/vp/products/123456

    # 5) 오늘의 골드박스(특가) 소재 뽑기
    python -m threadscout goldbox --limit 20
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Optional

from .collect import CollectError, get_token
from .coupang import CoupangError, PartnersClient, pick_best, search_via_apify
from .pipeline import PipelineOptions, run_pipeline
from .product import lexicon_terms
from .report import to_markdown, write_csv, write_html, write_json, write_markdown
from .score import Filters, ScoreWeights


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _add_scan_args(p: argparse.ArgumentParser) -> None:
    src = p.add_argument_group("수집")
    src.add_argument("--keyword", "-k", action="append", default=[],
                     help="검색 키워드(여러 번 지정 가능). 예: -k 'air fryer' -k 'kitchen gadget'")
    src.add_argument("--from-json", dest="from_json", default=None,
                     help="저장해둔 원시 JSON 으로 재분석(수집 건너뜀)")
    src.add_argument("--max-posts", type=int, default=50, help="키워드당 최대 수집 수 (기본 50)")
    src.add_argument("--sort", choices=("top", "recent"), default="top", help="Threads 검색 정렬")
    src.add_argument("--days", type=int, default=None, help="최근 N일 글만")
    src.add_argument("--actor", default=None, help="Apify 액터 (기본: futurizerush/meta-threads-scraper)")
    src.add_argument("--token", default=None, help="APIFY_TOKEN (환경변수 대신 직접 전달)")
    src.add_argument("--save-raw", dest="save_raw", default=None, help="원시 JSON 저장 경로")

    flt = p.add_argument_group("필터")
    flt.add_argument("--include-korean", action="store_true", help="한국어 글도 포함(기본은 해외 글만)")
    flt.add_argument("--lang", action="append", default=[], help="언어 한정(예: --lang en --lang ja)")
    flt.add_argument("--min-views", type=int, default=0, help="최소 조회수")
    flt.add_argument("--min-likes", type=int, default=0, help="최소 좋아요")
    flt.add_argument("--min-replies", type=int, default=0, help="최소 댓글 수")
    flt.add_argument("--max-followers", type=int, default=None,
                     help="팔로워 상한(따라할 수 있는 중소 계정만 보기)")
    flt.add_argument("--include-replies", action="store_true", help="답글도 포함")

    sc = p.add_argument_group("점수 가중치 (합이 1이 아니어도 자동 정규화)")
    sc.add_argument("--w-exposure", type=float, default=0.25, help="노출량")
    sc.add_argument("--w-share", type=float, default=0.25, help="공유율")
    sc.add_argument("--w-reply", type=float, default=0.25, help="댓글율")
    sc.add_argument("--w-reach", type=float, default=0.15, help="팔로워 대비 도달")
    sc.add_argument("--w-velocity", type=float, default=0.10, help="확산 속도")
    sc.add_argument("--top", type=int, default=20, help="상위 몇 건을 상세 분석할지")

    cp = p.add_argument_group("쿠팡 / 초안")
    cp.add_argument("--coupang", choices=("auto", "partners", "apify", "off"), default="auto",
                    help="쿠팡 매칭 방식 (auto: 파트너스 키 있으면 파트너스, 없으면 Apify)")
    cp.add_argument("--sub-id", default="threads", help="파트너스 subId(채널 추적용)")
    cp.add_argument("--max-matches", type=int, default=10, help="쿠팡 조회할 글 수")
    cp.add_argument("--no-drafts", action="store_true", help="한국어 초안 생성 건너뛰기")
    cp.add_argument("--no-translate", action="store_true", help="번역 없이 초안 생성")
    cp.add_argument("--drafts", type=int, default=5, help="초안 개수 (기본 5)")

    out = p.add_argument_group("출력")
    out.add_argument("--out-dir", default="output", help="리포트 저장 폴더 (기본 output/)")
    out.add_argument("--name", default=None, help="리포트 파일 이름(확장자 제외)")
    out.add_argument("--no-files", action="store_true", help="파일 저장 없이 화면 출력만")


def _options_from_args(args: argparse.Namespace) -> PipelineOptions:
    filters = Filters(
        exclude_korean=not args.include_korean,
        languages=tuple(args.lang),
        min_views=args.min_views,
        min_likes=args.min_likes,
        min_replies=args.min_replies,
        max_age_days=args.days,
        exclude_replies=not args.include_replies,
        max_followers=args.max_followers,
    )
    weights = ScoreWeights(
        exposure=args.w_exposure, share_rate=args.w_share, reply_rate=args.w_reply,
        reach=args.w_reach, velocity=args.w_velocity,
    )
    kwargs = dict(
        keywords=tuple(args.keyword),
        from_json=args.from_json,
        max_posts=args.max_posts,
        sort=args.sort,
        days=args.days,
        apify_token=args.token,
        save_raw_path=args.save_raw,
        filters=filters,
        weights=weights,
        top=args.top,
        coupang=args.coupang,
        coupang_sub_id=args.sub_id,
        max_matches=args.max_matches,
        make_drafts=not args.no_drafts,
        translate=not args.no_translate,
        draft_limit=args.drafts,
    )
    if args.actor:
        kwargs["actor"] = args.actor
    return PipelineOptions(**kwargs)


def cmd_scan(args: argparse.Namespace) -> int:
    if not args.keyword and not args.from_json:
        _log("검색 키워드가 필요합니다:  -k 'air fryer'   (또는 --from-json 으로 재분석)")
        return 2

    result = run_pipeline(_options_from_args(args), log=_log)

    if result["summary"].get("count", 0) == 0:
        _log("조건에 맞는 글이 없습니다.")
        print("\n".join(result.get("notes", [])))
        return 1

    print(to_markdown(result))

    if not args.no_files:
        stem = args.name or f"threadscout_{time.strftime('%Y%m%d_%H%M%S')}"
        base = os.path.join(args.out_dir, stem)
        paths = [
            write_markdown(result, base + ".md"),
            write_html(result, base + ".html"),
            write_csv(result, base + ".csv"),
            write_json(result, base + ".json"),
        ]
        _log("\n저장:")
        for path in paths:
            _log(f"  {path}")
    return 0


def cmd_coupang(args: argparse.Namespace) -> int:
    """검색어가 쿠팡에서 팔리는지 + 파트너스 링크."""
    client = PartnersClient.from_env(sub_id=args.sub_id)
    if client is None:
        _log("파트너스 키가 없어 Apify 로 조회합니다(제휴 링크 없음).")
        try:
            grouped = search_via_apify(args.keywords, token=get_token(args.token),
                                       max_per_keyword=args.limit)
        except (CollectError, CoupangError) as exc:
            _log(str(exc))
            return 1
        for keyword in args.keywords:
            best = pick_best(keyword, grouped.get(keyword, []))
            _print_match(keyword, best)
        return 0

    for keyword in args.keywords:
        try:
            products = client.search(keyword, limit=args.limit)
        except CoupangError as exc:
            _log(f"'{keyword}' 조회 실패: {exc}")
            continue
        _print_match(keyword, pick_best(keyword, products))
    return 0


def _print_match(keyword: str, product) -> None:  # noqa: ANN001
    if product is None:
        print(f"❌ {keyword}: 적합한 상품 없음")
        return
    price = f"{product.price:,}원" if product.price else "가격미상"
    commission = f" · 건당 약 {product.commission_per_sale:,}원" if product.commission_per_sale else ""
    rocket = " · 로켓배송" if product.is_rocket else ""
    print(f"✅ {keyword}: {product.name[:50]} ({price}{rocket}{commission})\n   {product.url}")


def cmd_link(args: argparse.Namespace) -> int:
    client = PartnersClient.from_env(sub_id=args.sub_id)
    if client is None:
        _log("COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY 환경변수가 필요합니다.")
        return 1
    try:
        mapping = client.deeplink(args.urls)
    except CoupangError as exc:
        _log(str(exc))
        return 1
    for original, short in mapping.items():
        print(f"{original}\n  → {short}")
    return 0


def cmd_goldbox(args: argparse.Namespace) -> int:
    client = PartnersClient.from_env(sub_id=args.sub_id)
    if client is None:
        _log("COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY 환경변수가 필요합니다.")
        return 1
    try:
        products = client.goldbox(limit=args.limit)
    except CoupangError as exc:
        _log(str(exc))
        return 1
    for product in products:
        price = f"{product.price:,}원" if product.price else "-"
        print(f"· {product.name[:60]} | {price} | {product.url}")
    return 0


def cmd_terms(_: argparse.Namespace) -> int:
    """제품 사전에 등록된 쿠팡 검색어 목록."""
    for term in lexicon_terms():
        print(term)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="threadscout",
        description="해외 스레드 노출/댓글/공유 분석 → 쿠팡 파트너스 판매 글 만들기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="스레드 수집·분석·쿠팡 매칭·초안 생성")
    _add_scan_args(scan)
    scan.set_defaults(func=cmd_scan)

    coupang = sub.add_parser("coupang", help="검색어의 쿠팡 판매 여부/링크 확인")
    coupang.add_argument("keywords", nargs="+", help="쿠팡 검색어(한국어)")
    coupang.add_argument("--limit", type=int, default=5)
    coupang.add_argument("--sub-id", default="threads")
    coupang.add_argument("--token", default=None, help="APIFY_TOKEN(파트너스 키 없을 때)")
    coupang.set_defaults(func=cmd_coupang)

    link = sub.add_parser("link", help="쿠팡 URL → 파트너스 딥링크")
    link.add_argument("urls", nargs="+")
    link.add_argument("--sub-id", default="threads")
    link.set_defaults(func=cmd_link)

    goldbox = sub.add_parser("goldbox", help="오늘의 골드박스 특가 목록")
    goldbox.add_argument("--limit", type=int, default=20)
    goldbox.add_argument("--sub-id", default="threads")
    goldbox.set_defaults(func=cmd_goldbox)

    terms = sub.add_parser("terms", help="제품 사전(쿠팡 검색어) 목록")
    terms.set_defaults(func=cmd_terms)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (CollectError, CoupangError, RuntimeError) as exc:
        _log(f"오류: {exc}")
        return 1
    except KeyboardInterrupt:
        _log("중단되었습니다.")
        return 130
    except BrokenPipeError:  # `| head` 등으로 출력이 잘린 경우
        return 0
