"""가사 교정(강제 정렬) · songbook 순수 로직 테스트 (whisper/openpyxl 불필요)."""

import pytest

from capcut_agent.lyrics import (
    LyricSegment,
    WordTiming,
    align_lyrics,
    _normalize_word,
)
from capcut_agent.songbook import (
    Song,
    clean_lyric_lines,
    mood_to_style,
    _parse_duration,
)


# --- 가사 클린업 --------------------------------------------------------
def test_clean_removes_section_tags_and_blanks():
    raw = "[Intro, Heavy Beat]\n\nI was born to win\n[Chorus]\nMade it now\n"
    assert clean_lyric_lines(raw) == ["I was born to win", "Made it now"]


def test_clean_keeps_or_drops_adlibs():
    raw = "Main line\n(Yeah, born to win)\n"
    assert clean_lyric_lines(raw, keep_adlibs=True) == ["Main line", "(Yeah, born to win)"]
    assert clean_lyric_lines(raw, keep_adlibs=False) == ["Main line"]


def test_clean_strips_inline_tags():
    raw = "[Verse 1] real words here"
    assert clean_lyric_lines(raw) == ["real words here"]


# --- 무드/기타 ----------------------------------------------------------
def test_mood_to_style():
    assert mood_to_style("각성") == "goosebump"
    assert mood_to_style("도약") == "energetic"
    assert mood_to_style("위로") == "dreamy"
    assert mood_to_style("모르는무드") == "goosebump"  # 기본값


def test_parse_duration():
    assert _parse_duration("1:54") == 114.0
    assert _parse_duration("3:39") == 219.0
    assert _parse_duration("1:00:00") == 3600.0
    assert _parse_duration("") is None
    assert _parse_duration("bad") is None


def test_song_helpers():
    song = Song(title="X", mood="도약", raw_lyrics="[Intro]\nrun it now\ngo all the way")
    assert song.lyric_lines() == ["run it now", "go all the way"]
    assert song.style() == "energetic"


def test_normalize_word():
    assert _normalize_word("Flyin'") == "flyin"
    assert _normalize_word("won't!") == "wont"
    assert _normalize_word("...") == ""


# --- 강제 정렬(핵심): 틀린 Whisper → 정답 교정 --------------------------
def _wt(seq):
    """(word, start, end) 튜플 목록 → WordTiming 목록."""
    return [WordTiming(w, s, e) for w, s, e in seq]


def test_align_corrects_text_and_transfers_timing():
    # Whisper 오인식: born→porn, win→when, look→luck, 잡음단어 'now'
    whisper = _wt([
        ("I", 0.0, 0.2), ("was", 0.2, 0.4), ("porn", 0.4, 0.7),
        ("to", 0.7, 0.9), ("when", 0.9, 1.2),
        ("never", 2.0, 2.3), ("luck", 2.3, 2.6), ("down", 2.6, 2.9), ("now", 2.9, 3.1),
    ])
    official = ["I was born to win", "Never look down"]
    segs = align_lyrics(official, whisper_words=whisper, duration=4.0)

    # 텍스트는 정답으로 교정
    assert [s.text for s in segs] == official
    # 타이밍은 Whisper 기준 (1줄 ~0s, 2줄 ~2s)
    assert segs[0].start < 0.5
    assert 1.8 < segs[1].start < 2.5
    # 시간순·비겹침
    assert segs[0].end <= segs[1].start


def test_align_interpolates_missing_official_words():
    # 정답에만 있는 단어(Whisper 누락)도 이웃 시각으로 보간되어 줄이 유지됨
    whisper = _wt([("hello", 0.0, 0.5), ("world", 3.0, 3.5)])
    official = ["hello brand new world"]  # brand, new 는 whisper 에 없음
    segs = align_lyrics(official, whisper_words=whisper, duration=4.0)
    assert len(segs) == 1
    assert segs[0].text == "hello brand new world"
    assert segs[0].start < 0.6 and segs[0].end > 2.5


def test_align_fallback_distribution_without_words():
    official = ["line one", "line two three four"]
    segs = align_lyrics(
        official,
        whisper_segments=[LyricSegment(0.0, 6.0, "noise")],
        duration=6.0,
    )
    assert [s.text for s in segs] == official
    # 단어 수 비례: 둘째 줄(4단어)이 첫째(2단어)보다 길다
    assert (segs[1].end - segs[1].start) > (segs[0].end - segs[0].start)


def test_align_empty_official():
    assert align_lyrics([], whisper_words=_wt([("a", 0, 1)]), duration=2.0) == []
