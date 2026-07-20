"""다중 클립 배치 · 가사 구간 강조 · 다중 배경 설정 테스트 (pyJianYingDraft 불필요)."""

import os

import pytest

from capcut_agent.audio import BeatMap, select_transition_points
from capcut_agent.config import AgentConfig, from_dict
from capcut_agent.draft_builder import assign_clips


# --- assign_clips --------------------------------------------------------
def test_assign_sequential_round_robin():
    assert assign_clips(5, 3, "sequential") == [0, 1, 2, 0, 1]


def test_assign_single_clip():
    assert assign_clips(4, 1) == [0, 0, 0, 0]


def test_assign_empty():
    assert assign_clips(0, 3) == []
    assert assign_clips(5, 0) == []


def test_assign_shuffle_uses_all_and_no_immediate_repeat():
    out = assign_clips(30, 4, "shuffle", seed=7)
    assert len(out) == 30
    assert set(out) == {0, 1, 2, 3}          # 모든 클립 사용
    assert all(a != b for a, b in zip(out, out[1:]))  # 연속 중복 없음


def test_assign_shuffle_is_deterministic_with_seed():
    a = assign_clips(20, 5, "shuffle", seed=42)
    b = assign_clips(20, 5, "shuffle", seed=42)
    assert a == b


def test_assign_shuffle_balanced():
    # 클립을 한 바퀴씩 균등 사용하는지(개수 편차 <= 1)
    out = assign_clips(40, 4, "shuffle", seed=1)
    counts = [out.count(i) for i in range(4)]
    assert max(counts) - min(counts) <= 1


# --- 가사 구간 강조 ------------------------------------------------------
def test_emphasis_windows_mark_strong():
    beats = [0.5, 1.0, 1.5, 2.0, 2.5]
    bm = BeatMap(duration=3.0, tempo=120.0, beats=beats,
                 strengths=[0.1] * 5, downbeats=[])
    # 가사 구간 [0.9, 1.6] 안의 비트(1.0, 1.5)만 강박이어야 함
    pts = select_transition_points(bm, min_gap=0.0, subdivision=1,
                                   emphasis_windows=[(0.9, 1.6)])
    strong = {p.time for p in pts if p.strong}
    assert strong == {1.0, 1.5}


def test_no_emphasis_when_windows_empty():
    beats = [0.5, 1.0, 1.5]
    bm = BeatMap(duration=2.0, tempo=120.0, beats=beats,
                 strengths=[0.1, 0.1, 0.1], downbeats=[])
    pts = select_transition_points(bm, min_gap=0.0, subdivision=1,
                                   strong_percentile=0.99, emphasis_windows=[])
    assert not any(p.strong for p in pts)


# --- 다중 배경 설정 ------------------------------------------------------
def test_from_dict_accepts_background_paths():
    cfg = from_dict({
        "audio_path": "a.mp3",
        "draft_folder": "/d",
        "background_paths": ["c1.mp4", "c2.mp4"],
    })
    assert cfg.resolved_backgrounds() == ["c1.mp4", "c2.mp4"]


def test_from_dict_requires_some_background():
    with pytest.raises(ValueError):
        from_dict({"audio_path": "a.mp3", "draft_folder": "/d"})


def test_resolved_backgrounds_merges_and_dedupes():
    cfg = AgentConfig(
        audio_path="a.mp3", draft_folder="/d",
        background_path="single.mp4",
        background_paths=["c1.mp4", "single.mp4"],  # single 중복
    )
    out = cfg.resolved_backgrounds()
    assert out == ["c1.mp4", "single.mp4"]  # 중복 제거, 순서 유지


def test_resolved_backgrounds_from_dir(tmp_path):
    (tmp_path / "b.mp4").write_bytes(b"x")
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("ignore")  # 미디어 아님 → 제외
    cfg = AgentConfig(audio_path="a.mp3", draft_folder="/d",
                      background_dir=str(tmp_path))
    out = [os.path.basename(p) for p in cfg.resolved_backgrounds()]
    assert out == ["a.png", "b.mp4"]  # 이름순 정렬, txt 제외


def test_invalid_clip_order_raises():
    with pytest.raises(ValueError):
        AgentConfig(audio_path="a.mp3", draft_folder="/d",
                    background_path="c.mp4", clip_order="random")
