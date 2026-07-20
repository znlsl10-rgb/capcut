"""이중 자막(영한) 순수 로직 테스트 (번역기/pyCapCut 불필요)."""

from capcut_agent.lyrics import LyricSegment, clamp_segments_to_duration
from capcut_agent.translate import attach_secondary, build_secondary


def _segs():
    return [
        LyricSegment(0.0, 2.0, "I was born to win"),
        LyricSegment(2.0, 4.0, "Never looking down"),
        LyricSegment(4.0, 6.0, "This is my time"),
    ]


def test_attach_secondary_pairs_in_order():
    out = attach_secondary(_segs(), ["나는 이기려 태어났어", "결코 고개 숙이지 않아", "지금이 내 시간"])
    assert out[0].secondary == "나는 이기려 태어났어"
    assert out[2].secondary == "지금이 내 시간"
    # 원문/타이밍 보존
    assert out[0].text == "I was born to win"
    assert out[1].start == 2.0


def test_attach_secondary_shorter_ko_leaves_none():
    out = attach_secondary(_segs(), ["첫 줄만"])
    assert out[0].secondary == "첫 줄만"
    assert out[1].secondary is None and out[2].secondary is None


def test_attach_secondary_skips_blank():
    out = attach_secondary(_segs(), ["가", "", "다"])
    assert out[1].secondary is None


def test_build_secondary_without_source_is_passthrough():
    out = build_secondary(_segs())
    assert all(s.secondary is None for s in out)


def test_build_secondary_from_file(tmp_path):
    f = tmp_path / "ko.txt"
    f.write_text("가\n나\n다\n", encoding="utf-8")
    out = build_secondary(_segs(), ko_file=str(f))
    assert [s.secondary for s in out] == ["가", "나", "다"]


def test_clamp_preserves_secondary():
    segs = [LyricSegment(0.0, 2.0, "hello", secondary="안녕")]
    out = clamp_segments_to_duration(segs, 10.0)
    assert out[0].secondary == "안녕"
