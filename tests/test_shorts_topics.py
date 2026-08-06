"""shorts.topics 결정론적 로테이션 테스트."""

from __future__ import annotations

from shorts.topics import TOPICS, categories, daily_plan, pick_topics


def test_pick_is_deterministic():
    a = pick_topics(5, seed="2026-08")
    b = pick_topics(5, seed="2026-08")
    assert [t.title for t in a] == [t.title for t in b]


def test_pick_different_seed_differs():
    a = [t.title for t in pick_topics(5, seed="A")]
    b = [t.title for t in pick_topics(5, seed="B")]
    assert a != b  # 매우 높은 확률로 다름(뱅크가 충분)


def test_pick_no_duplicates_within_bank_size():
    picked = pick_topics(len(TOPICS), seed="x")
    titles = [t.title for t in picked]
    assert len(titles) == len(set(titles))  # 서로소 스텝 → 뱅크 전체 순회 시 중복 없음


def test_pick_clamped_to_pool_size():
    assert len(pick_topics(1000, seed="x")) == len(TOPICS)


def test_category_filter():
    picked = pick_topics(3, seed="x", category="부")
    assert all(t.category == "부" for t in picked)


def test_categories_nonempty():
    assert "마인드셋" in categories()


def test_daily_plan_shape():
    plan = daily_plan(7, per_day=2, seed="wk")
    assert set(plan.keys()) == set(range(7))
    assert all(len(v) == 2 for v in plan.values())
