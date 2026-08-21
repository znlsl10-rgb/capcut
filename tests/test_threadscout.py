"""threadscout 순수 로직 테스트 (네트워크·Apify·쿠팡 API 불필요)."""

import json
import time

import pytest

from threadscout.analyze import analyze, hook_stats, term_lift
from threadscout.coupang import (
    CoupangProduct,
    _hmac_authorization,
    match_score,
    pick_best,
)
from threadscout.draft import build_draft
from threadscout.models import detect_script, hangul_ratio, normalize_posts
from threadscout.pipeline import PipelineOptions, run_pipeline
from threadscout.product import commerce_intent, extract_lead, find_categories
from threadscout.report import to_html, to_markdown, write_csv
from threadscout.score import (
    Filters,
    ScoreWeights,
    apply_filters,
    estimate_views_per_like,
    percentile_ranks,
    score_posts,
)

NOW = time.time()


def make_raw(**over):
    """futurizerush 액터 형식의 원시 레코드."""
    base = {
        "post_id": over.get("post_id", "1"),
        "post_url": over.get("post_url", "https://www.threads.com/@user/post/1"),
        "username": "user",
        "followers_count": 5000,
        "text_content": "I bought this air fryer and it changed my kitchen. Worth it?",
        "created_at_timestamp": int(NOW - 3600 * 24),
        "view_count": 100000,
        "like_count": 2000,
        "reply_count": 300,
        "repost_count": 100,
        "quote_count": 20,
        "share_count": 80,
        "is_reply": False,
        "is_repost": False,
        "language": "en",
        "has_media": True,
    }
    base.update(over)
    return base


# --- 정규화 --------------------------------------------------------------
def test_normalize_futurizerush_fields():
    (post,) = normalize_posts([make_raw()])
    assert post.username == "user"
    assert post.views == 100000
    assert post.replies == 300
    assert post.spread == 200          # repost + quote + share
    assert post.engagement == 2500
    assert post.has_media is True
    assert post.created_at is not None


def test_normalize_camelcase_actor_fields():
    """igview/burbn 계열(camelCase, takenAt, directReplyCount)도 같은 형태로."""
    raw = {
        "postId": "abc",
        "postUrl": "https://www.threads.com/@x/post/abc",
        "username": "x",
        "captionText": "hello world",
        "takenAt": int(NOW - 7200),
        "likeCount": 10,
        "directReplyCount": 4,
        "repostCount": 2,
        "quoteCount": 1,
        "reshareCount": 3,
    }
    (post,) = normalize_posts([raw])
    assert post.post_id == "abc" and post.likes == 10 and post.replies == 4
    assert post.spread == 6            # repost 2 + quote 1 + share(reshare) 3
    assert post.views is None          # 조회수 미제공


def test_normalize_dedup_and_skip_profiles():
    rows = [make_raw(), make_raw(), {"record_type": "profile", "username": "someone"}]
    assert len(normalize_posts(rows)) == 1


def test_normalize_abbreviated_counts():
    (post,) = normalize_posts([make_raw(like_count="1.2K", view_count="3M")])
    assert post.likes == 1200 and post.views == 3_000_000


def test_hashtags_from_text():
    (post,) = normalize_posts([make_raw(text_content="best #AirFryer deal #kitchen")])
    assert post.hashtags == ["airfryer", "kitchen"]


# --- 언어 ---------------------------------------------------------------
def test_detect_script():
    assert detect_script("완전 대박입니다") == "ko"
    assert detect_script("this is a test") == "en"
    assert detect_script("これはテストです") == "ja"


def test_hangul_ratio():
    assert hangul_ratio("안녕하세요") == 1.0
    assert hangul_ratio("hello") == 0.0
    assert 0.4 < hangul_ratio("hello 안녕하세") < 0.6


# --- 필터 ---------------------------------------------------------------
def test_filters_drop_korean_and_replies():
    posts = normalize_posts([
        make_raw(post_id="1", post_url="u1"),
        make_raw(post_id="2", post_url="u2", text_content="한국어 게시물입니다 완전 좋아요"),
        make_raw(post_id="3", post_url="u3", is_reply=True),
    ])
    kept = apply_filters(posts, Filters())
    assert [p.post_id for p in kept] == ["1"]


def test_filters_thresholds():
    posts = normalize_posts([
        make_raw(post_id="1", post_url="u1", view_count=500),
        make_raw(post_id="2", post_url="u2", view_count=50000),
    ])
    kept = apply_filters(posts, Filters(min_views=1000))
    assert [p.post_id for p in kept] == ["2"]


def test_filters_max_followers():
    posts = normalize_posts([
        make_raw(post_id="1", post_url="u1", followers_count=1_000_000),
        make_raw(post_id="2", post_url="u2", followers_count=3000),
    ])
    kept = apply_filters(posts, Filters(max_followers=100_000))
    assert [p.post_id for p in kept] == ["2"]


# --- 점수 ---------------------------------------------------------------
def test_percentile_ranks_basic():
    assert percentile_ranks([1, 2, 3]) == [0.0, 0.5, 1.0]


def test_percentile_ranks_ties_and_missing():
    ranks = percentile_ranks([5, 5, 9, None])
    assert ranks[0] == ranks[1]        # 동점은 같은 값
    assert ranks[2] == 1.0             # 최대값
    assert ranks[3] == 0.0             # 결측은 최하위


def test_estimate_views_per_like_median():
    posts = normalize_posts([
        make_raw(post_id="1", post_url="u1", view_count=1000, like_count=10),   # 100
        make_raw(post_id="2", post_url="u2", view_count=4000, like_count=100),  # 40
        make_raw(post_id="3", post_url="u3", view_count=600, like_count=10),    # 60
    ])
    assert estimate_views_per_like(posts) == 60.0


def test_score_prefers_high_reply_and_share_rate():
    """같은 노출이면 댓글·공유가 많은 쪽이 위로."""
    posts = normalize_posts([
        make_raw(post_id="hot", post_url="hot", reply_count=5000, share_count=3000),
        make_raw(post_id="cold", post_url="cold", reply_count=5, share_count=1),
    ])
    scored = score_posts(posts)
    assert scored[0].post.post_id == "hot"
    assert scored[0].score > scored[1].score


def test_score_views_estimated_when_missing():
    posts = normalize_posts([
        {"postUrl": "a", "captionText": "no views here", "likeCount": 100, "takenAt": int(NOW - 3600)},
        {"postUrl": "b", "captionText": "also none", "likeCount": 10, "takenAt": int(NOW - 3600)},
    ])
    scored = score_posts(posts)
    assert all(row.views_estimated for row in scored)
    assert scored[0].effective_views > 0


def test_weights_change_ranking():
    posts = normalize_posts([
        make_raw(post_id="reach", post_url="reach", followers_count=100, view_count=50000,
                 reply_count=1, share_count=0),
        make_raw(post_id="talk", post_url="talk", followers_count=500000, view_count=50000,
                 reply_count=4000, share_count=0),
    ])
    by_reply = score_posts(posts, ScoreWeights(exposure=0, share_rate=0, reply_rate=1, reach=0, velocity=0))
    by_reach = score_posts(posts, ScoreWeights(exposure=0, share_rate=0, reply_rate=0, reach=1, velocity=0))
    assert by_reply[0].post.post_id == "talk"
    assert by_reach[0].post.post_id == "reach"


# --- 분석 ---------------------------------------------------------------
def _many_posts(n=12):
    rows = []
    for i in range(n):
        rows.append(make_raw(
            post_id=str(i), post_url=f"u{i}",
            text_content=("Why does nobody talk about this air fryer?" if i % 2 == 0
                          else "I bought a yoga mat yesterday and it is fine."),
            view_count=10000 * (i + 1), reply_count=10 * (i + 1), like_count=100 * (i + 1),
        ))
    return normalize_posts(rows)


def test_hook_stats_and_analyze():
    scored = score_posts(_many_posts())
    hooks = hook_stats(scored, min_count=2)
    assert hooks and all(h.count >= 2 for h in hooks)
    result = analyze(scored)
    assert result["summary"]["count"] == 12
    assert "hooks" in result and "keywords" in result


def test_term_lift_finds_top_terms():
    scored = score_posts(_many_posts())
    terms = term_lift(scored, min_top_count=1)
    assert any(t.term in ("fryer", "air", "nobody", "talk") for t in terms)


# --- 제품 추출 -----------------------------------------------------------
def test_commerce_intent_scores_purchase_signals():
    score, signals = commerce_intent("I bought this for $40 and it's worth it")
    assert score >= 4 and "구매 경험" in signals


def test_find_categories_maps_to_korean():
    assert "air fryer" in find_categories("this AIR FRYER is great")


def test_extract_lead_builds_korean_search_terms():
    (post,) = normalize_posts([make_raw(
        text_content="I bought the Ninja air fryer for $99 and it's worth it.")])
    lead = extract_lead(post)
    assert lead.sellable
    assert any("에어프라이어" in term for term in lead.search_terms)


def test_extract_lead_not_sellable_for_random_post():
    (post,) = normalize_posts([make_raw(text_content="Good morning everyone, lovely weather today.")])
    assert extract_lead(post).sellable is False


# --- 쿠팡 ---------------------------------------------------------------
def test_match_score_and_pick_best():
    products = [
        CoupangProduct(name="샤오미 무선청소기", url="u1", price=90000),
        CoupangProduct(name="에어프라이어 5L 대용량", url="u2", price=60000, is_rocket=True),
    ]
    assert match_score("에어프라이어", "에어프라이어 5L 대용량") == 1.0
    best = pick_best("에어프라이어", products)
    assert best is not None and best.url == "u2"


def test_pick_best_returns_none_when_no_match():
    assert pick_best("전동칫솔", [CoupangProduct(name="양말 3켤레", url="u")]) is None


def test_commission_estimate_uses_category_rate():
    product = CoupangProduct(name="선크림", url="u", price=20000, category="뷰티")
    assert product.commission_rate == 0.07
    assert product.commission_per_sale == 1400


def test_hmac_authorization_shape():
    header = _hmac_authorization("GET", "/path?keyword=abc", "AK", "SK")
    assert header.startswith("CEA algorithm=HmacSHA256, access-key=AK, signed-date=")
    assert ", signature=" in header and len(header.rsplit("=", 1)[1]) == 64


# --- 초안 ---------------------------------------------------------------
def test_build_draft_includes_disclosure_and_cta():
    (post,) = normalize_posts([make_raw(
        text_content="I bought this air fryer for $99. Worth it? Here is why it changed my kitchen.")])
    row = score_posts([post])[0]
    lead = extract_lead(post)
    draft = build_draft(row, lead, None, translate=False)
    text = draft.text
    assert "쿠팡 파트너스 활동의 일환" in text
    assert "👇" in text                      # 댓글 유도
    assert draft.hashtags
    assert any("찾지 못했" in w for w in draft.warnings)


def test_build_draft_with_product_uses_affiliate_link():
    from threadscout.coupang import CoupangMatch

    (post,) = normalize_posts([make_raw(text_content="I bought this air fryer, worth it.")])
    row = score_posts([post])[0]
    product = CoupangProduct(name="쿠쿠 에어프라이어", url="https://link.coupang.com/a/xyz",
                             price=79000, is_rocket=True, affiliate=True)
    match = CoupangMatch(post_url=post.url, keyword="에어프라이어", found=True, product=product)
    draft = build_draft(row, extract_lead(post), match, translate=False)
    assert "https://link.coupang.com/a/xyz" in draft.text
    assert "79,000원" in draft.text
    assert not any("제휴 링크가 아닙니다" in w for w in draft.warnings)


# --- 파이프라인 / 리포트 -------------------------------------------------
def test_run_pipeline_from_json(tmp_path):
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps([r.__dict__ if hasattr(r, "__dict__") else r
                                    for r in [make_raw(post_id=str(i), post_url=f"u{i}",
                                                       view_count=1000 * (i + 1))
                                              for i in range(6)]]), encoding="utf-8")
    options = PipelineOptions(from_json=str(raw_path), coupang="off", make_drafts=True,
                              translate=False, top=5, draft_limit=2)
    result = run_pipeline(options)
    assert result["summary"]["count"] == 6
    assert len(result["posts"]) == 5
    assert result["drafts"] and "쿠팡 파트너스" in result["drafts"][0]["text"]


def test_run_pipeline_empty_result(tmp_path):
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps([make_raw(text_content="한국어만 있는 글입니다 여기")]), encoding="utf-8")
    result = run_pipeline(PipelineOptions(from_json=str(raw_path), coupang="off"))
    assert result["summary"]["count"] == 0
    assert result["notes"]


def test_reports_render(tmp_path):
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps([make_raw(post_id=str(i), post_url=f"u{i}") for i in range(4)]),
                        encoding="utf-8")
    result = run_pipeline(PipelineOptions(from_json=str(raw_path), coupang="off", translate=False))
    md, html = to_markdown(result), to_html(result)
    assert "# 해외 스레드 분석 리포트" in md
    assert "<html" in html and "노출·댓글·공유 상위 글" in html
    csv_path = write_csv(result, tmp_path / "out.csv")
    assert csv_path.exists() and "score" in csv_path.read_text(encoding="utf-8-sig").splitlines()[0]


# --- 벤치마킹 엑셀 -------------------------------------------------------
def test_hook_label_classification():
    from threadscout.benchmark import hook_label

    assert hook_label("Unpopular opinion: air fryers are overrated") == "논쟁형"
    assert hook_label("5 things I wish I knew") == "리스트형"
    assert hook_label("How to fix your sleep") == "방법형"
    assert hook_label("Is this worth it?") == "질문형"
    assert hook_label("I bought a yoga mat") == "스토리형"


def test_takeaways_mentions_reply_rate():
    from threadscout.benchmark import takeaways

    note = takeaways({"reply_rate_pct": 1.5, "text": "x" * 300})
    assert "댓글율" in note


def test_write_xlsx_creates_all_sheets(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from threadscout.benchmark import write_xlsx

    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps([make_raw(post_id=str(i), post_url=f"u{i}",
                                             view_count=10000 * (i + 1)) for i in range(6)]),
                        encoding="utf-8")
    result = run_pipeline(PipelineOptions(from_json=str(raw_path), coupang="off",
                                          translate=False, top=5, draft_limit=2))
    out = write_xlsx(result, tmp_path / "board.xlsx")
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["1_벤치마킹", "2_훅패턴", "3_키워드", "4_계정", "5_쿠팡매칭", "6_초안"]
    board = wb["1_벤치마킹"]
    assert board["A3"].value == "#"          # 헤더는 3행
    assert board.max_row >= 8                # 상위 5건 + 헤더 + 평균행


# --- 키워드 프리셋 -------------------------------------------------------
def test_preset_keywords_merges_and_dedups():
    from threadscout.presets import preset_keywords, preset_names

    assert "beauty" in preset_names()
    merged = preset_keywords(["beauty", "beauty", "fitness"])
    assert "skincare routine" in merged
    assert "creatine" in merged
    assert len(merged) == len(set(merged))


def test_preset_unknown_name_is_ignored():
    from threadscout.presets import preset_keywords

    assert preset_keywords(["nope"]) == []


def test_cli_scan_combines_preset_and_keywords():
    from threadscout.cli import build_parser, _options_from_args

    args = build_parser().parse_args(
        ["scan", "--preset", "beauty", "-k", "air fryer", "--coupang", "off"])
    options = _options_from_args(args)
    assert "skincare routine" in options.keywords
    assert options.keywords[-1] == "air fryer"


def test_beauty_lexicon_covers_common_terms():
    from threadscout.product import PRODUCT_LEXICON

    for term in ("niacinamide", "sunscreen", "retinol", "biotin", "melatonin", "gua sha"):
        assert term in PRODUCT_LEXICON
