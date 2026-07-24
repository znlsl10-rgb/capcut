"""AI 소재 최소 제작 계획 순수 로직 테스트."""

import math

from capcut_agent.genplan import (
    GenerationPlan,
    min_clips_needed,
    plan_generation,
    summarize_plan,
)


def test_min_clips_basic():
    # 100s 곡, 5s 클립, 0.5 슬로우 → 클립당 10s → 10개.
    assert min_clips_needed(100, 5, 0.5) == 10


def test_min_clips_rounds_up():
    # 45s 곡, 5s 클립, 0.5 → 클립당 10s → 4.5 → 올림 5개.
    assert min_clips_needed(45, 5, 0.5) == 5


def test_min_clips_no_slow():
    # 슬로우 없음(1.0) → 클립당 = clip_len → 100/5 = 20개.
    assert min_clips_needed(100, 5, 1.0) == 20


def test_min_clips_variety():
    # 다양성 1.5x → 10 * 1.5 = 15개.
    assert min_clips_needed(100, 5, 0.5, variety=1.5) == 15


def test_min_clips_at_least_one():
    assert min_clips_needed(3, 5, 0.5) == 1
    assert min_clips_needed(0, 5, 0.5) == 1
    assert min_clips_needed(100, 0, 0.5) == 1


def test_min_clips_clamps_slow_floor():
    # slow_floor 범위 밖이면 클램프(0.1~1.0).
    assert min_clips_needed(100, 5, 0.0) == min_clips_needed(100, 5, 0.1)
    assert min_clips_needed(100, 5, 5.0) == min_clips_needed(100, 5, 1.0)


def test_plan_generation_fields():
    plan = plan_generation(100, clip_len=5, slow_floor=0.5)
    assert isinstance(plan, GenerationPlan)
    assert plan.min_clips == 10
    assert plan.coverage_per_clip == 10.0
    assert plan.raw_footage == 50.0
    # 원본 50s 를 100s 곡에 → 0.5x.
    assert plan.effective_speed == 0.5


def test_plan_generation_enough_footage_full_speed():
    # 최소보다 많이(다양성) 만들면 속도가 1.0 에 가까워짐.
    plan = plan_generation(100, clip_len=5, slow_floor=0.5, variety=2.0)
    assert plan.min_clips == 20
    assert plan.raw_footage == 100.0
    assert plan.effective_speed == 1.0


def test_plan_generation_json_roundtrip():
    plan = plan_generation(60, 5, 0.5)
    d = plan.to_dict()
    assert d["min_clips"] == plan.min_clips
    assert set(d) == {
        "song_duration", "clip_len", "slow_floor", "variety",
        "coverage_per_clip", "min_clips", "raw_footage", "effective_speed",
    }


def test_summarize_plan_runs():
    text = summarize_plan(plan_generation(100, 5, 0.5))
    assert "최소 제작 계획" in text
    assert "최소 10개 생성" in text


def test_plan_matches_draft_builder_speed():
    # genplan 의 effective_speed 가 draft_builder.compute_global_speed 와 일치.
    from capcut_agent.draft_builder import compute_global_speed

    plan = plan_generation(80, clip_len=5, slow_floor=0.5)
    expected = compute_global_speed(plan.raw_footage, 80, 0.5)
    assert plan.effective_speed == round(expected, 3)
