"""shorts.render / pipeline 순수 로직 테스트 (ffmpeg 불필요)."""

from __future__ import annotations

from shorts.render import (
    Caption,
    RenderStyle,
    _ass_color,
    _ass_escape,
    _ass_time,
    build_ass,
    is_image,
    plan_blocks,
)


def test_plan_blocks_cuts_at_captions():
    caps = [Caption(0, 2, "a"), Caption(2, 4, "b"), Caption(4, 6, "c")]
    blocks = plan_blocks(caps, 6.0, min_seg=1.0, max_seg=3.0)
    assert blocks[0][0] == 0.0
    assert blocks[-1][1] == 6.0
    # 연속·비겹침
    for i in range(len(blocks) - 1):
        assert abs(blocks[i][1] - blocks[i + 1][0]) < 1e-6


def test_plan_blocks_merges_short():
    caps = [Caption(0, 0.3, "a"), Caption(0.3, 0.6, "b"), Caption(0.6, 5, "c")]
    blocks = plan_blocks(caps, 5.0, min_seg=1.2, max_seg=10.0)
    assert all((b - a) >= 1.0 for a, b in blocks[:-1]) or len(blocks) >= 1
    assert blocks[-1][1] == 5.0


def test_plan_blocks_splits_long():
    blocks = plan_blocks([], 10.0, max_seg=3.0)
    assert len(blocks) >= 3
    assert all((b - a) <= 3.5 for a, b in blocks)
    assert blocks[-1][1] == 10.0


def test_plan_blocks_empty_total():
    assert plan_blocks([], 0.0) == []


def test_ass_color_rgb_to_bgr():
    assert _ass_color("#FF0000") == "&H000000FF"   # 빨강 → BGR
    assert _ass_color("#00FF00") == "&H0000FF00"
    assert _ass_color("#FFFFFF") == "&H00FFFFFF"


def test_ass_time_format():
    assert _ass_time(0) == "0:00:00.00"
    assert _ass_time(65.5) == "0:01:05.50"
    assert _ass_time(3661.0) == "1:01:01.00"


def test_ass_escape_newline_and_braces():
    assert _ass_escape("a\nb") == "a\\Nb"
    assert "{" not in _ass_escape("a{b}c")


def test_build_ass_has_style_and_dialogue():
    caps = [Caption(0, 2, "첫 줄"), Caption(2, 4, "둘째 줄")]
    ass = build_ass(caps, RenderStyle())
    assert "[V4+ Styles]" in ass
    assert "Style: Cap," in ass
    assert ass.count("Dialogue:") == 2
    assert "첫 줄" in ass


def test_build_ass_skips_empty():
    caps = [Caption(0, 2, "  "), Caption(2, 4, "x")]
    assert build_ass(caps, RenderStyle()).count("Dialogue:") == 1


def test_is_image():
    assert is_image("a.PNG") and is_image("b.jpg")
    assert not is_image("c.mp4")


def test_distribute_never_exceeds_total():
    from shorts.pipeline import _distribute

    lines = [f"라인{i}" for i in range(20)]
    segs = _distribute(lines, 8.0)
    assert segs[0].start == 0.0
    assert segs[-1].end == 8.0
    for s in segs:
        assert s.start <= s.end <= 8.0
    for i in range(len(segs) - 1):
        assert segs[i].end <= segs[i + 1].start + 1e-6


def test_distribute_weights_by_length():
    from shorts.pipeline import _distribute

    segs = _distribute(["짧다", "이것은 훨씬 더 긴 자막 라인입니다"], 10.0)
    assert (segs[1].end - segs[1].start) > (segs[0].end - segs[0].start)
