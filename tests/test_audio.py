"""audio 모듈 순수 로직 테스트 (librosa 불필요)."""

from capcut_agent.audio import (
    BeatMap,
    TransitionPoint,
    segment_boundaries,
    select_transition_points,
    _percentile,
)


def _beatmap(n=8, step=0.5, duration=None, strengths=None, downbeats=None):
    beats = [round((i + 1) * step, 3) for i in range(n)]
    return BeatMap(
        duration=duration if duration is not None else beats[-1] + step,
        tempo=120.0,
        beats=beats,
        strengths=strengths if strengths is not None else [1.0] * n,
        downbeats=downbeats or [],
    )


def test_select_respects_min_gap():
    bm = _beatmap(n=8, step=0.25)  # 비트 간격 0.25s
    pts = select_transition_points(bm, min_gap=0.5, subdivision=1)
    times = [p.time for p in pts]
    # 인접 간격이 모두 0.5 이상이어야 함
    assert all(b - a >= 0.5 - 1e-6 for a, b in zip(times, times[1:]))
    assert len(times) >= 1


def test_subdivision_thins_out_beats():
    bm = _beatmap(n=8, step=0.5)
    every = select_transition_points(bm, min_gap=0.0, subdivision=1)
    every_other = select_transition_points(bm, min_gap=0.0, subdivision=2)
    assert len(every_other) < len(every)


def test_downbeats_marked_strong():
    bm = _beatmap(n=4, step=0.5, downbeats=[1.0, 2.0])
    pts = select_transition_points(bm, min_gap=0.0, subdivision=1)
    strong_times = {p.time for p in pts if p.strong}
    assert 1.0 in strong_times and 2.0 in strong_times


def test_high_strength_marked_strong():
    bm = _beatmap(n=4, step=0.5, strengths=[0.1, 0.2, 0.95, 0.3])
    pts = select_transition_points(bm, min_gap=0.0, subdivision=1, strong_percentile=0.7)
    strong = [p.time for p in pts if p.strong]
    assert 1.5 in strong  # 세 번째 비트(세기 0.95)


def test_max_count_caps_and_keeps_time_order():
    bm = _beatmap(n=10, step=0.5, strengths=[i / 10 for i in range(10)])
    pts = select_transition_points(bm, min_gap=0.0, subdivision=1, max_count=3)
    assert len(pts) == 3
    times = [p.time for p in pts]
    assert times == sorted(times)


def test_boundaries_wrap_full_duration():
    pts = [TransitionPoint(1.0), TransitionPoint(2.0)]
    bounds = segment_boundaries(pts, duration=3.0)
    assert bounds[0] == 0.0
    assert bounds[-1] == 3.0
    assert bounds == [0.0, 1.0, 2.0, 3.0]
    # 세그먼트 개수 = 전환 수 + 1
    assert len(bounds) - 1 == len(pts) + 1


def test_boundaries_ignore_out_of_range_points():
    pts = [TransitionPoint(1.0), TransitionPoint(5.0)]  # 5.0 은 duration 밖
    bounds = segment_boundaries(pts, duration=3.0)
    assert bounds == [0.0, 1.0, 3.0]


def test_empty_beats_returns_empty():
    bm = BeatMap(duration=10.0, tempo=0.0, beats=[], strengths=[], downbeats=[])
    assert select_transition_points(bm) == []


def test_percentile_basic():
    assert _percentile([0, 1], 0.0) == 0
    assert _percentile([0, 1], 1.0) == 1
    assert abs(_percentile([0, 10], 0.5) - 5) < 1e-9
