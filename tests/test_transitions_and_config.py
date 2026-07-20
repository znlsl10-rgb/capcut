"""transitions/config/draft_builder 순수 로직 테스트 (pyJianYingDraft 불필요)."""

import pytest

from capcut_agent.audio import BeatMap
from capcut_agent.config import AgentConfig, from_dict
from capcut_agent.draft_builder import _hex_to_rgb, _source_window, plan_summary
from capcut_agent.lyrics import LyricSegment
from capcut_agent.transitions import get_preset, list_presets


# --- transitions ---------------------------------------------------------
def test_presets_exist():
    names = list_presets()
    assert "goosebump" in names
    for n in names:
        p = get_preset(n)
        assert p.transitions and p.strong_transitions and p.text_intro


def test_unknown_preset_raises():
    with pytest.raises(KeyError):
        get_preset("nonexistent-style")


def test_pick_transition_rotates_and_switches_pool():
    p = get_preset("goosebump")
    normal = p.pick_transition(0, strong=False)
    strong = p.pick_transition(0, strong=True)
    assert normal in p.transitions
    assert strong in p.strong_transitions
    # 순환 확인
    assert p.pick_transition(len(p.transitions), False) == p.pick_transition(0, False)


def test_pick_bg_and_text_intro():
    p = get_preset("goosebump")
    assert p.pick_text_intro(False) == p.text_intro
    assert p.pick_text_intro(True) == p.text_strong_intro
    assert p.pick_bg_intro(True) == p.bg_strong_intro


# --- config --------------------------------------------------------------
def test_from_dict_requires_core_fields():
    with pytest.raises(ValueError):
        from_dict({"audio_path": "a.mp3"})  # background/draft_folder 누락


def test_from_dict_collects_extra():
    cfg = from_dict(
        {
            "audio_path": "a.mp3",
            "background_path": "b.mp4",
            "draft_folder": "/d",
            "unknown_key": 123,
        }
    )
    assert cfg.extra["unknown_key"] == 123


def test_config_validation():
    with pytest.raises(ValueError):
        AgentConfig(audio_path="a", background_path="b", draft_folder="d", width=0)


def test_resolved_output_srt_default():
    cfg = AgentConfig(audio_path="a", background_path="b", draft_folder="d", draft_name="foo")
    assert cfg.resolved_output_srt() == "foo.srt"


# --- draft_builder pure helpers -----------------------------------------
def test_hex_to_rgb():
    assert _hex_to_rgb("#FFFFFF") == (1.0, 1.0, 1.0)
    assert _hex_to_rgb("#000000") == (0.0, 0.0, 0.0)
    r, g, b = _hex_to_rgb("#FF0000")
    assert (round(r), round(g), round(b)) == (1, 0, 0)


class _FakeTimerange:
    def __init__(self, start, duration):
        self.start = start
        self.duration = duration


class _FakeMaterial:
    def __init__(self, duration):
        self.duration = duration


def test_source_window_photo_is_fixed():
    tr = _source_window(_FakeTimerange, _FakeMaterial(10_000_000), 500_000, 3_000_000, is_photo=True)
    assert tr.start == 0 and tr.duration == 500_000


def test_source_window_video_loops():
    mat = _FakeMaterial(2_000_000)  # 2s 소재
    # 타임라인 3s 위치 → 3s % 2s = 1s 지점에서 0.5s 잘라씀
    tr = _source_window(_FakeTimerange, mat, 500_000, 3_000_000, is_photo=False)
    assert tr.start == 1_000_000 and tr.duration == 500_000


def test_source_window_clamps_at_end():
    mat = _FakeMaterial(2_000_000)
    # 1.8s 지점에서 0.5s 잘라쓰려 하면 끝을 넘으므로 뒤로 당김
    tr = _source_window(_FakeTimerange, mat, 500_000, 1_800_000, is_photo=False)
    assert tr.start + tr.duration <= mat.duration


def test_source_window_segment_longer_than_material():
    mat = _FakeMaterial(1_000_000)
    tr = _source_window(_FakeTimerange, mat, 3_000_000, 0, is_photo=False)
    assert tr.start == 0 and tr.duration == mat.duration


# --- plan_summary (통합, 순수) ------------------------------------------
def test_plan_summary_runs_without_libs():
    cfg = AgentConfig(
        audio_path="a.mp3", background_path="b.mp4", draft_folder="/d", style="goosebump"
    )
    bm = BeatMap(
        duration=8.0,
        tempo=120.0,
        beats=[round(0.5 * (i + 1), 3) for i in range(15)],
        strengths=[1.0] * 15,
        downbeats=[2.0, 4.0],
    )
    lyrics = [LyricSegment(0.0, 2.0, "가사 한 줄"), LyricSegment(2.0, 4.0, "다음 줄")]
    summary = plan_summary(cfg, bm, lyrics)
    assert "goosebump" in summary
    assert "가사 자막 2줄" in summary
