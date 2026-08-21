"""리포트 출력 — JSON / CSV / Markdown / HTML."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

CSV_COLUMNS = [
    "score", "url", "username", "followers", "views", "views_estimated",
    "likes", "replies", "reposts", "quotes", "shares",
    "reply_rate_pct", "share_rate_pct", "reach_multiple", "views_per_hour",
    "language", "created_at", "coupang_found", "coupang_keyword",
    "coupang_product", "coupang_price", "coupang_url", "text",
]


def _flat_row(post: Dict[str, Any]) -> Dict[str, Any]:
    coupang = post.get("coupang") or {}
    product = (coupang.get("product") or {}) if coupang else {}
    return {
        "score": post.get("score"),
        "url": post.get("url"),
        "username": post.get("username"),
        "followers": post.get("followers"),
        "views": post.get("effective_views"),
        "views_estimated": post.get("views_estimated"),
        "likes": post.get("likes"),
        "replies": post.get("replies"),
        "reposts": post.get("reposts"),
        "quotes": post.get("quotes"),
        "shares": post.get("shares"),
        "reply_rate_pct": post.get("reply_rate_pct"),
        "share_rate_pct": post.get("share_rate_pct"),
        "reach_multiple": post.get("reach_multiple"),
        "views_per_hour": post.get("views_per_hour"),
        "language": post.get("language"),
        "created_at": post.get("created_at"),
        "coupang_found": coupang.get("found"),
        "coupang_keyword": coupang.get("keyword"),
        "coupang_product": product.get("name"),
        "coupang_price": product.get("price"),
        "coupang_url": product.get("url"),
        "text": (post.get("text") or "").replace("\n", " ")[:500],
    }


def write_json(result: Dict[str, Any], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def write_csv(result: Dict[str, Any], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for post in result.get("posts", []):
            writer.writerow(_flat_row(post))
    return out


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return "\n".join(lines)


def to_markdown(result: Dict[str, Any]) -> str:
    summary = result.get("summary") or {}
    analysis = result.get("analysis") or {}
    opts = result.get("options") or {}
    out: List[str] = []

    out.append("# 해외 스레드 분석 리포트")
    kw = ", ".join(opts.get("keywords") or []) or opts.get("from_json") or "-"
    out.append(f"\n- 키워드: **{kw}**")
    out.append(f"- 분석 대상: **{summary.get('count', 0)}건** "
               f"(중앙 노출 {summary.get('median_views', 0):,} · "
               f"평균 댓글율 {summary.get('avg_reply_rate_pct', 0)}% · "
               f"평균 공유율 {summary.get('avg_share_rate_pct', 0)}%)")
    langs = ", ".join(f"{d['language']}({d['count']})" for d in summary.get("languages", []))
    if langs:
        out.append(f"- 언어 구성: {langs}")

    # 상위 글
    out.append("\n## 1. 노출·댓글·공유 상위 글")
    rows = []
    for i, post in enumerate(result.get("posts", [])[:20], 1):
        coupang = post.get("coupang") or {}
        product = (coupang.get("product") or {}) if coupang else {}
        rows.append([
            i, post.get("score"), f"@{post.get('username')}",
            f"{int(post.get('effective_views') or 0):,}",
            post.get("likes"), post.get("replies"),
            (post.get("reposts") or 0) + (post.get("quotes") or 0) + (post.get("shares") or 0),
            f"{post.get('reply_rate_pct')}%", f"{post.get('share_rate_pct')}%",
            "✅" if coupang.get("found") else ("❌" if coupang else "-"),
            (product.get("name") or "")[:24],
            f"[링크]({post.get('url')})",
        ])
    out.append(_table(
        ["#", "점수", "계정", "노출", "좋아요", "댓글", "공유", "댓글율", "공유율", "쿠팡", "상품", "원문"],
        rows,
    ))

    # 패턴
    def _group_table(title: str, key: str) -> None:
        groups = analysis.get(key) or []
        if not groups:
            return
        out.append(f"\n### {title}")
        out.append(_table(
            ["구분", "글수", "평균점수", "배수", "중앙노출", "댓글율", "공유율"],
            [[g["name"], g["count"], g["avg_score"], f"×{g['lift']}",
              f"{g['median_views']:,}", f"{g['avg_reply_rate_pct']}%", f"{g['avg_share_rate_pct']}%"]
             for g in groups],
        ))

    out.append("\n## 2. 왜 터졌나 — 공통 패턴")
    _group_table("훅(첫 줄) 유형별", "hooks")
    _group_table("글 길이별", "lengths")
    _group_table("사진/영상 유무", "media")
    _group_table("발행 시간대(KST)", "hours")

    keywords = analysis.get("keywords") or []
    if keywords:
        out.append("\n### 상위권에서 유독 많이 나온 단어")
        out.append(_table(["단어", "상위 등장", "하위 등장", "lift", "평균점수"],
                          [[k["term"], k["top_count"], k["rest_count"], f"×{k['lift']}", k["avg_score"]]
                           for k in keywords[:15]]))

    authors = analysis.get("authors") or []
    if authors:
        out.append("\n### 벤치마킹할 계정")
        out.append(_table(["계정", "글수", "평균점수", "중앙노출", "팔로워", "최고글"],
                          [[f"@{a['username']}", a["posts"], a["avg_score"], f"{a['median_views']:,}",
                            a.get("followers") or "-", a["best_url"]] for a in authors[:10]]))

    # 쿠팡 매칭
    matches = result.get("matches") or []
    if matches:
        out.append("\n## 3. 쿠팡 판매 매칭")
        rows = []
        for m in matches:
            product = m.get("product") or {}
            rows.append([
                m.get("keyword"),
                "✅ 판매중" if m.get("found") else "❌ 없음/불일치",
                (product.get("name") or "")[:40],
                f"{product.get('price'):,}원" if product.get("price") else "-",
                f"{product.get('commission_rate_pct', '-')}%",
                f"{product.get('commission_per_sale'):,}원" if product.get("commission_per_sale") else "-",
                product.get("url") or m.get("note") or "-",
            ])
        out.append(_table(["검색어", "상태", "상품", "가격", "수수료율(추정)", "건당 수익(추정)", "링크"], rows))

    # 초안
    drafts = result.get("drafts") or []
    if drafts:
        out.append("\n## 4. 스레드 업로드용 한국어 초안")
        for i, draft in enumerate(drafts, 1):
            out.append(f"\n### 초안 {i} — 원문: {draft.get('source_url')}")
            if draft.get("warnings"):
                out.append("> ⚠️ " + " / ".join(draft["warnings"]))
            out.append("```text\n" + (draft.get("text") or "") + "\n```")

    notes = result.get("notes") or []
    if notes:
        out.append("\n## 참고")
        out.extend(f"- {n}" for n in notes)
    return "\n".join(out) + "\n"


def write_markdown(result: Dict[str, Any], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_markdown(result), encoding="utf-8")
    return out


# --- HTML ---------------------------------------------------------------
_HTML_CSS = """
:root { color-scheme: light dark; --bg:#0f1115; --card:#171a21; --fg:#e8eaed; --muted:#9aa0a6;
        --line:#262b34; --acc:#4f8cff; --ok:#2ecc71; --no:#ff6b6b; }
@media (prefers-color-scheme: light) {
  :root { --bg:#f6f7f9; --card:#fff; --fg:#1b1d22; --muted:#5f6368; --line:#e3e6ea; }
}
* { box-sizing: border-box; }
body { margin:0; padding:24px; background:var(--bg); color:var(--fg);
       font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 10px; }
h3 { font-size:14px; margin:18px 0 8px; color:var(--muted); }
.wrap { max-width:1180px; margin:0 auto; }
.cards { display:flex; flex-wrap:wrap; gap:10px; margin:14px 0 4px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; min-width:130px; }
.card b { display:block; font-size:19px; }
.card span { color:var(--muted); font-size:12px; }
table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line);
        border-radius:10px; overflow:hidden; font-size:13px; }
th,td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
th { background:rgba(127,127,127,.08); font-weight:600; white-space:nowrap; }
tr:last-child td { border-bottom:none; }
td.num, th.num { text-align:right; white-space:nowrap; }
.tw { max-width:420px; color:var(--muted); }
a { color:var(--acc); text-decoration:none; } a:hover { text-decoration:underline; }
.ok { color:var(--ok); } .no { color:var(--no); }
.scroll { overflow-x:auto; }
pre { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px;
      white-space:pre-wrap; word-break:break-word; }
.warn { color:#f5a623; font-size:12px; margin:6px 0; }
.muted { color:var(--muted); font-size:12px; }
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _html_table(headers: Sequence[str], rows: Sequence[Sequence[str]], num_cols: Sequence[int] = ()) -> str:
    head = "".join(
        f'<th class="{"num" if i in num_cols else ""}">{_esc(h)}</th>' for i, h in enumerate(headers)
    )
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="{"num" if i in num_cols else ""}">{c}</td>' for i, c in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def to_html(result: Dict[str, Any]) -> str:
    summary = result.get("summary") or {}
    analysis = result.get("analysis") or {}
    opts = result.get("options") or {}
    kw = ", ".join(opts.get("keywords") or []) or (opts.get("from_json") or "-")

    parts: List[str] = [
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>해외 스레드 분석 리포트</title>",
        f"<style>{_HTML_CSS}</style></head><body><div class='wrap'>",
        f"<h1>해외 스레드 분석 리포트</h1><p class='muted'>키워드: {_esc(kw)}</p>",
        "<div class='cards'>",
        f"<div class='card'><b>{summary.get('count', 0):,}</b><span>분석 글</span></div>",
        f"<div class='card'><b>{summary.get('median_views', 0):,}</b><span>중앙 노출</span></div>",
        f"<div class='card'><b>{summary.get('avg_reply_rate_pct', 0)}%</b><span>평균 댓글율</span></div>",
        f"<div class='card'><b>{summary.get('avg_share_rate_pct', 0)}%</b><span>평균 공유율</span></div>",
        f"<div class='card'><b>{len([m for m in result.get('matches', []) if m.get('found')])}</b>"
        f"<span>쿠팡 매칭</span></div>",
        "</div>",
    ]

    # 상위 글
    rows = []
    for i, post in enumerate(result.get("posts", [])[:30], 1):
        coupang = post.get("coupang") or {}
        product = (coupang.get("product") or {}) if coupang else {}
        cou = "-"
        if coupang:
            cou = (f"<span class='ok'>✅ {_esc((product.get('name') or '')[:20])}</span>"
                   if coupang.get("found") else "<span class='no'>❌</span>")
        rows.append([
            str(i), f"{post.get('score')}", _esc("@" + str(post.get("username") or "")),
            f"{int(post.get('effective_views') or 0):,}",
            f"{post.get('likes'):,}", f"{post.get('replies'):,}",
            f"{(post.get('reposts') or 0) + (post.get('quotes') or 0) + (post.get('shares') or 0):,}",
            f"{post.get('reply_rate_pct')}%", f"{post.get('share_rate_pct')}%", cou,
            f"<div class='tw'>{_esc((post.get('text') or '')[:220])}</div>",
            f"<a href='{_esc(post.get('url'))}' target='_blank' rel='noopener'>원문</a>",
        ])
    parts.append("<h2>1. 노출·댓글·공유 상위 글</h2>")
    parts.append(_html_table(
        ["#", "점수", "계정", "노출", "좋아요", "댓글", "공유", "댓글율", "공유율", "쿠팡", "내용", "링크"],
        rows, num_cols=(0, 1, 3, 4, 5, 6, 7, 8)))

    # 패턴
    parts.append("<h2>2. 왜 터졌나 — 공통 패턴</h2>")
    for title, key in (("훅(첫 줄) 유형별", "hooks"), ("글 길이별", "lengths"),
                       ("사진/영상 유무", "media"), ("발행 시간대(KST)", "hours")):
        groups = analysis.get(key) or []
        if not groups:
            continue
        parts.append(f"<h3>{_esc(title)}</h3>")
        parts.append(_html_table(
            ["구분", "글수", "평균점수", "배수", "중앙노출", "댓글율", "공유율"],
            [[_esc(g["name"]), str(g["count"]), str(g["avg_score"]), f"×{g['lift']}",
              f"{g['median_views']:,}", f"{g['avg_reply_rate_pct']}%", f"{g['avg_share_rate_pct']}%"]
             for g in groups], num_cols=(1, 2, 3, 4, 5, 6)))

    keywords = analysis.get("keywords") or []
    if keywords:
        parts.append("<h3>상위권에서 유독 많이 나온 단어</h3>")
        parts.append(_html_table(
            ["단어", "상위", "하위", "lift", "평균점수"],
            [[_esc(k["term"]), str(k["top_count"]), str(k["rest_count"]), f"×{k['lift']}", str(k["avg_score"])]
             for k in keywords[:20]], num_cols=(1, 2, 3, 4)))

    # 쿠팡
    matches = result.get("matches") or []
    if matches:
        parts.append("<h2>3. 쿠팡 판매 매칭</h2>")
        rows = []
        for m in matches:
            product = m.get("product") or {}
            link = (f"<a href='{_esc(product.get('url'))}' target='_blank' rel='noopener'>상품</a>"
                    if product.get("url") else _esc(m.get("note")))
            rows.append([
                _esc(m.get("keyword")),
                "<span class='ok'>판매중</span>" if m.get("found") else "<span class='no'>없음</span>",
                _esc((product.get("name") or "")[:50]),
                f"{product['price']:,}원" if product.get("price") else "-",
                f"{product.get('commission_rate_pct', '-')}%",
                f"{product['commission_per_sale']:,}원" if product.get("commission_per_sale") else "-",
                link,
            ])
        parts.append(_html_table(
            ["검색어", "상태", "상품", "가격", "수수료율(추정)", "건당 수익(추정)", "링크"],
            rows, num_cols=(3, 4, 5)))

    # 초안
    drafts = result.get("drafts") or []
    if drafts:
        parts.append("<h2>4. 스레드 업로드용 한국어 초안</h2>")
        for i, draft in enumerate(drafts, 1):
            parts.append(f"<h3>초안 {i} · <a href='{_esc(draft.get('source_url'))}' "
                         f"target='_blank' rel='noopener'>원문</a> "
                         f"<span class='muted'>({draft.get('char_count', 0)}자)</span></h3>")
            for warning in draft.get("warnings") or []:
                parts.append(f"<div class='warn'>⚠️ {_esc(warning)}</div>")
            parts.append(f"<pre>{_esc(draft.get('text'))}</pre>")

    notes = result.get("notes") or []
    if notes:
        parts.append("<h2>참고</h2><ul class='muted'>")
        parts.extend(f"<li>{_esc(n)}</li>" for n in notes)
        parts.append("</ul>")

    parts.append("</div></body></html>")
    return "".join(parts)


def write_html(result: Dict[str, Any], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_html(result), encoding="utf-8")
    return out
