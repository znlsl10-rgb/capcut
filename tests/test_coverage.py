"""커버리지(슬로우 채움) 순수 로직 테스트 (pyCapCut 불필요)."""

import pytest

from capcut_agent.config import AgentConfig
from capcut_agent.draft_builder import _coverage_source, compute_global_speed


class _TR:
    def __init__(self, start, duration):
        self.start = start
        self.duration = duration


class _Mat:
    def __init__(self, duration):
        self.duration = duration


# --- 전역 속도 ----------------------------------------------------------
def test_global_speed_enough_footage_is_full():
    # 소재가 곡보다 길면 정상 속도
    assert compute_global_speed(120.0, 100.0, 0.5) == 1.0


def test_global_speed_scales_to_fill():
    # 소재 40s, 곡 100s → 0.4 지만 하한 0.5 로 클램프
    assert compute_global_speed(40.0, 100.0, 0.5) == 0.5


def test_global_speed_partial_fill():
    # 소재 70s, 곡 100s → 0.7 (하한 위)
    assert abs(compute_global_speed(70.0, 100.0, 0.5) - 0.7) < 1e-9


def test_global_speed_edge():
    assert compute_global_speed(0, 100, 0.5) == 1.0
    assert compute_global_speed(50, 0, 0.5) == 1.0


# --- 커버리지 소스 구간 -------------------------------------------------
def test_coverage_source_slows_video():
    # target 2s, speed 0.5 → 소스 1s 만 잡아 느리게 재생
    mat = _Mat(10_000_000)  # 10s 소재
    tr = _coverage_source(_TR, mat, 2_000_000, 0, 0.5, is_photo=False)
    assert tr.duration == 1_000_000  # 2s * 0.5


def test_coverage_source_photo_unchanged():
    mat = _Mat(10_000_000)
    tr = _coverage_source(_TR, mat, 2_000_000, 0, 0.5, is_photo=True)
    assert tr.duration == 2_000_000  # 이미지는 슬로우 무의미 → target 그대로


def test_coverage_source_speed_one_is_normal():
    mat = _Mat(10_000_000)
    tr = _coverage_source(_TR, mat, 2_000_000, 0, 1.0, is_photo=False)
    assert tr.duration == 2_000_000


def test_coverage_source_clip_shorter_than_needed():
    # 소재 0.5s, target 2s, speed 0.5 → 필요한 1s 보다 소재가 짧음 → 전체 사용
    mat = _Mat(500_000)
    tr = _coverage_source(_TR, mat, 2_000_000, 0, 0.5, is_photo=False)
    assert tr.duration == 500_000 and tr.start == 0


def test_coverage_source_advances_within_clip():
    # 커서가 진행하면 소재 뒷부분을 사용
    mat = _Mat(10_000_000)
    tr = _coverage_source(_TR, mat, 2_000_000, 3_000_000, 0.5, is_photo=False)
    assert tr.start == 3_000_000 and tr.duration == 1_000_000


# --- config 검증 ---------------------------------------------------------
def test_config_footage_mode_validation():
    with pytest.raises(ValueError):
        AgentConfig(audio_path="a", background_path="b", draft_folder="d", footage_mode="bad")


def test_config_slow_floor_validation():
    with pytest.raises(ValueError):
        AgentConfig(audio_path="a", background_path="b", draft_folder="d", slow_floor=2.0)
