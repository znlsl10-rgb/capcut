"""파이프라인 — 수집 → 필터 → 점수 → 제품추출 → 쿠팡매칭 → 한국어 초안.

CLI 와 웹 UI 가 공통으로 쓰는 진입점.

    result = run_pipeline(PipelineOptions(keywords=["air fryer"], top=10))
    result["drafts"][0]["text"]   # 스레드에 붙여넣을 한국어 글
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import analyze as analyze_mod
from .collect import THREADS_ACTOR, collect_threads, get_token, load_json, save_raw
from .coupang import CoupangMatch, PartnersClient, pick_best, search_via_apify
from .draft import build_drafts
from .models import normalize_posts
from .product import ProductLead, extract_leads
from .score import Filters, ScoredPost, ScoreWeights, apply_filters, score_posts

Logger = Callable[[str], None]


@dataclass
class PipelineOptions:
    # 수집
    keywords: Sequence[str] = ()
    from_json: Optional[str] = None
    max_posts: int = 50
    sort: str = "top"
    days: Optional[int] = None
    actor: str = THREADS_ACTOR
    apify_token: Optional[str] = None
    save_raw_path: Optional[str] = None
    # 필터/점수
    filters: Filters = field(default_factory=Filters)
    weights: ScoreWeights = field(default_factory=ScoreWeights)
    top: int = 20
    # 쿠팡
    coupang: str = "auto"          # auto | partners | apify | off
    coupang_sub_id: str = "threads"
    max_matches: int = 10
    # 초안
    make_drafts: bool = True
    translate: bool = True
    draft_limit: int = 5


def _noop(_: str) -> None:
    return None


def match_coupang(
    rows: Sequence[ScoredPost],
    leads: Dict[str, ProductLead],
    *,
    mode: str = "auto",
    apify_token: Optional[str] = None,
    sub_id: str = "threads",
    limit: int = 10,
    log: Logger = _noop,
) -> Dict[str, CoupangMatch]:
    """상위 글의 제품 검색어를 쿠팡에서 조회 → 판매 여부/링크 확인."""
    if mode == "off":
        return {}

    targets = [row for row in rows if leads.get(row.post.url, None) and leads[row.post.url].sellable][:limit]
    if not targets:
        log("[coupang] 제품으로 연결할 만한 글이 없습니다.")
        return {}

    client = PartnersClient.from_env(sub_id=sub_id) if mode in ("auto", "partners") else None
    if mode == "partners" and client is None:
        raise RuntimeError("COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY 환경변수가 필요합니다.")

    matches: Dict[str, CoupangMatch] = {}

    if client is not None:
        log(f"[coupang] 파트너스 API 로 {len(targets)}건 조회")
        for row in targets:
            lead = leads[row.post.url]
            keyword = lead.search_terms[0]
            try:
                products = client.search(keyword, limit=5)
            except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 막지 않도록
                log(f"[coupang] '{keyword}' 조회 실패: {exc}")
                matches[row.post.url] = CoupangMatch(row.post.url, keyword, False, note=str(exc))
                continue
            best = pick_best(keyword, products)
            matches[row.post.url] = CoupangMatch(
                post_url=row.post.url,
                keyword=keyword,
                found=best is not None,
                product=best,
                alternatives=[p for p in products[:3] if p is not best],
                note="" if best else "검색 결과에 적합한 상품 없음",
            )
        return matches

    # 파트너스 키가 없으면 Apify 로 '판매 여부'만 확인
    if mode in ("auto", "apify") and apify_token:
        keywords = []
        for row in targets:
            kw = leads[row.post.url].search_terms[0]
            if kw not in keywords:
                keywords.append(kw)
        log(f"[coupang] Apify 액터로 {len(keywords)}개 검색어 조회 (제휴 링크 없음)")
        try:
            grouped = search_via_apify(keywords, token=apify_token, max_per_keyword=5)
        except Exception as exc:  # noqa: BLE001
            log(f"[coupang] Apify 쿠팡 조회 실패: {exc}")
            return {}
        for row in targets:
            keyword = leads[row.post.url].search_terms[0]
            products = grouped.get(keyword, [])
            best = pick_best(keyword, products)
            matches[row.post.url] = CoupangMatch(
                post_url=row.post.url,
                keyword=keyword,
                found=best is not None,
                product=best,
                alternatives=[p for p in products[:3] if p is not best],
                note="" if best else "검색 결과에 적합한 상품 없음",
            )
        return matches

    log("[coupang] 쿠팡 조회를 건너뜁니다(파트너스 키·Apify 토큰 없음).")
    return matches


def run_pipeline(options: PipelineOptions, *, log: Logger = _noop) -> Dict[str, Any]:
    """전체 파이프라인 실행 → 리포트/웹에서 쓰는 결과 dict."""
    # 1) 수집
    if options.from_json:
        log(f"[collect] 로컬 JSON 로드: {options.from_json}")
        raw = load_json(options.from_json)
        token = (options.apify_token or "").strip() or None
    else:
        token = get_token(options.apify_token)
        log(f"[collect] Threads 수집: {', '.join(options.keywords)}")
        raw = collect_threads(
            options.keywords,
            token=token,
            max_posts=options.max_posts,
            sort=options.sort,
            days=options.days,
            actor=options.actor,
            log=log,
        )
    log(f"[collect] 원시 {len(raw)}건")
    if options.save_raw_path:
        path = save_raw(raw, options.save_raw_path)
        log(f"[collect] 원시 데이터 저장: {path}")

    # 2) 정규화 + 필터
    posts = normalize_posts(raw)
    kept = apply_filters(posts, options.filters)
    log(f"[filter] {len(posts)}건 → {len(kept)}건 (해외/노출/기간 조건)")
    if not kept:
        return {
            "summary": {"count": 0},
            "options": _options_dict(options),
            "posts": [], "analysis": {"summary": {"count": 0}},
            "leads": [], "matches": [], "drafts": [],
            "notes": ["조건에 맞는 글이 없습니다. 필터를 완화하거나 키워드를 바꿔보세요."],
        }

    # 3) 점수
    scored = score_posts(kept, options.weights)
    top_rows = scored[: options.top]
    log(f"[score] 상위 {len(top_rows)}건 선정 (1위 {top_rows[0].score:.1f}점)")

    # 4) 제품 추출
    leads_list = extract_leads([row.post for row in top_rows])
    leads = {lead.post_url: lead for lead in leads_list}
    sellable = [lead for lead in leads_list if lead.sellable]
    log(f"[product] 판매 연결 가능 글 {len(sellable)}/{len(leads_list)}건")

    # 5) 쿠팡 매칭
    matches = match_coupang(
        top_rows, leads,
        mode=options.coupang,
        apify_token=token,
        sub_id=options.coupang_sub_id,
        limit=options.max_matches,
        log=log,
    )
    found = sum(1 for m in matches.values() if m.found)
    if matches:
        log(f"[coupang] 쿠팡 판매 확인 {found}/{len(matches)}건")

    # 6) 한국어 초안
    drafts = []
    if options.make_drafts:
        draft_rows = [row for row in top_rows if leads.get(row.post.url) and leads[row.post.url].sellable]
        draft_rows = draft_rows or top_rows
        drafts = build_drafts(draft_rows, leads, matches,
                              translate=options.translate, limit=options.draft_limit)
        log(f"[draft] 한국어 초안 {len(drafts)}건 생성")

    analysis = analyze_mod.analyze(scored)

    return {
        "options": _options_dict(options),
        "summary": analysis["summary"],
        "analysis": analysis,
        "posts": [_post_row(row, leads.get(row.post.url), matches.get(row.post.url)) for row in top_rows],
        "leads": [lead.to_dict() for lead in leads_list],
        "matches": [m.to_dict() for m in matches.values()],
        "drafts": [d.to_dict() for d in drafts],
        "notes": _notes(scored, matches),
    }


def _post_row(row: ScoredPost, lead: Optional[ProductLead], match: Optional[CoupangMatch]) -> Dict[str, Any]:
    data = row.to_dict()
    data["product"] = lead.to_dict() if lead else None
    data["coupang"] = match.to_dict() if match else None
    return data


def _options_dict(options: PipelineOptions) -> Dict[str, Any]:
    return {
        "keywords": list(options.keywords),
        "from_json": options.from_json,
        "max_posts": options.max_posts,
        "sort": options.sort,
        "days": options.days,
        "actor": options.actor,
        "top": options.top,
        "coupang": options.coupang,
        "weights": options.weights.normalized().as_dict(),
        "filters": {
            "exclude_korean": options.filters.exclude_korean,
            "languages": list(options.filters.languages),
            "min_views": options.filters.min_views,
            "min_likes": options.filters.min_likes,
            "min_replies": options.filters.min_replies,
            "max_age_days": options.filters.max_age_days,
            "max_followers": options.filters.max_followers,
        },
    }


def _notes(scored: Sequence[ScoredPost], matches: Dict[str, CoupangMatch]) -> List[str]:
    notes: List[str] = []
    estimated = sum(1 for r in scored if r.views_estimated)
    if estimated:
        notes.append(
            f"조회수를 제공하지 않는 글 {estimated}건은 좋아요 기반 추정치로 계산했습니다"
            " (액터를 futurizerush/meta-threads-scraper 로 두면 실제 조회수를 받습니다)."
        )
    if matches and not any(m.product and m.product.affiliate for m in matches.values()):
        notes.append(
            "제휴 링크가 아직 없습니다 — COUPANG_ACCESS_KEY/COUPANG_SECRET_KEY 를 설정하면"
            " 파트너스 링크까지 자동 생성됩니다."
        )
    notes.append("쿠팡 파트너스 링크를 붙인 글에는 대가성 문구가 반드시 들어가야 합니다(초안에 자동 포함).")
    return notes
