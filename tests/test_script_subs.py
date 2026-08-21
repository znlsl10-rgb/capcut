"""대본 → 타임드 자막 순수 로직 테스트."""

from capcut_agent.script_subs import (
    distribute_lines,
    parse_script,
    script_to_segments,
)


# --- parse_script --------------------------------------------------------
def test_parse_basic_lines():
    text = "첫 번째 줄\n두 번째 줄\n\n세 번째 줄"
    assert parse_script(text) == ["첫 번째 줄", "두 번째 줄", "세 번째 줄"]


def test_parse_skips_srt_index_and_timeline():
    text = "1\n00:00:01,000 --> 00:00:03,000\n안녕하세요\n"
    assert parse_script(text) == ["안녕하세요"]


def test_parse_splits_long_sentence():
    long = "This is the first sentence. This is the second one."
    out = parse_script(long, max_len=34)
    assert len(out) == 2                       # 문장 종결부호 기준 2줄로 분할
    assert all(len(x) <= 34 for x in out)


def test_parse_word_wrap_when_no_punctuation():
    long = "word " * 20  # 100자, 구두점 없음
    out = parse_script(long.strip(), max_len=24)
    assert len(out) > 1
    assert all(len(x) <= 24 for x in out)


# --- distribute_lines ----------------------------------------------------
def test_distribute_even():
    lines = ["a", "b", "c", "d"]
    segs = distribute_lines(lines, 40.0)
    assert len(segs) == 4
    assert segs[0].start == 0.0
    # 균등 10초 간격.
    assert abs(segs[1].start - 10.0) < 0.01
    assert segs[-1].end <= 40.0


def test_distribute_monotonic_and_within_duration():
    lines = [f"line{i}" for i in range(10)]
    segs = distribute_lines(lines, 30.0)
    for a, b in zip(segs, segs[1:]):
        assert a.start <= b.start
        assert a.end <= b.end + 0.001
    assert all(s.end <= 30.0 for s in segs)


def test_distribute_with_beats_snaps():
    lines = ["a", "b", "c"]
    beats = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    segs = distribute_lines(lines, 6.0, beats=beats)
    assert len(segs) == 3
    # 시작이 비트 값들 중 하나에 스냅됨.
    for s in segs:
        assert any(abs(s.start - b) < 0.01 for b in beats)


def test_distribute_empty():
    assert distribute_lines([], 10.0) == []
    assert distribute_lines(["a"], 0.0) == []


def test_distribute_respects_min_dur():
    # 많은 줄을 짧은 길이에 → 최소 노출 시간 보장(겹치더라도 end>start).
    lines = [f"l{i}" for i in range(20)]
    segs = distribute_lines(lines, 5.0, min_dur=0.8)
    assert all(s.end > s.start for s in segs)


# --- script_to_segments --------------------------------------------------
def test_script_to_segments_end_to_end():
    text = "안녕하세요\n오늘은 스포츠카를 소개합니다\n끝"
    segs = script_to_segments(text, 30.0)
    assert len(segs) == 3
    assert segs[0].text == "안녕하세요"
    assert segs[0].start == 0.0
