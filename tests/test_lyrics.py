"""lyrics 모듈 순수 로직 테스트 (whisper 불필요)."""

import pytest

from capcut_agent.lyrics import (
    LyricSegment,
    _format_timestamp,
    clamp_segments_to_duration,
    segments_to_srt,
)


def test_format_timestamp():
    assert _format_timestamp(0) == "00:00:00,000"
    assert _format_timestamp(1.5) == "00:00:01,500"
    assert _format_timestamp(3661.234) == "01:01:01,234"
    assert _format_timestamp(-5) == "00:00:00,000"


def test_segments_to_srt_basic():
    segs = [
        LyricSegment(0.0, 1.0, "첫 줄"),
        LyricSegment(1.0, 2.5, "둘째 줄"),
    ]
    srt = segments_to_srt(segs)
    assert "1\n00:00:00,000 --> 00:00:01,000\n첫 줄" in srt
    assert "2\n00:00:01,000 --> 00:00:02,500\n둘째 줄" in srt
    assert srt.endswith("\n")


def test_segments_to_srt_skips_empty_and_reindexes():
    segs = [
        LyricSegment(0.0, 1.0, "  "),   # 공백 → 스킵
        LyricSegment(1.0, 2.0, "실제"),
    ]
    srt = segments_to_srt(segs)
    assert srt.startswith("1\n")       # 인덱스 1부터 다시
    assert "실제" in srt
    assert srt.count("-->") == 1


def test_clamp_trims_to_duration():
    segs = [LyricSegment(0.0, 5.0, "a"), LyricSegment(5.0, 12.0, "b")]
    out = clamp_segments_to_duration(segs, duration=8.0)
    assert out[-1].end <= 8.0


def test_clamp_removes_overlap():
    segs = [LyricSegment(0.0, 3.0, "a"), LyricSegment(2.0, 4.0, "b")]
    out = clamp_segments_to_duration(segs, duration=10.0)
    # 둘째 세그먼트 시작이 첫째 끝 이상으로 밀림
    assert out[1].start >= out[0].end


def test_clamp_drops_zero_length():
    segs = [LyricSegment(5.0, 5.0, "zero"), LyricSegment(1.0, 2.0, "ok")]
    out = clamp_segments_to_duration(segs, duration=10.0)
    texts = [s.text for s in out]
    assert "ok" in texts


def test_invalid_segment_raises():
    with pytest.raises(ValueError):
        LyricSegment(2.0, 1.0, "역전")
