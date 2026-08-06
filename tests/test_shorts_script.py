"""shorts.script 순수 로직 테스트 (라이브러리 불필요)."""

from __future__ import annotations

from shorts.script import (
    MotivationScript,
    parse_script,
    split_captions,
    estimate_seconds,
)


def test_parse_with_markers_roles():
    raw = "[hook] 첫 문장\n[body] 본문1\n본문2\n[cta] 구독하세요"
    s = parse_script(raw, topic="테스트")
    assert s.topic == "테스트"
    assert s.hook() == "첫 문장"
    assert s.body() == ["본문1", "본문2"]
    assert s.cta() == "구독하세요"


def test_parse_without_markers_heuristic():
    raw = "강한 훅 문장\n중간 메시지\n좋아요와 구독 부탁해요"
    s = parse_script(raw)
    assert s.lines[0].role == "hook"
    assert s.lines[-1].role == "cta"  # 구독 힌트 → CTA 승격
    assert s.hook() == "강한 훅 문장"


def test_parse_without_markers_no_cta():
    raw = "훅\n메시지 하나\n메시지 둘"
    s = parse_script(raw)
    assert s.cta() is None
    assert s.body() == ["메시지 하나", "메시지 둘"]


def test_narration_text_joins_spoken_lines():
    s = parse_script("[hook] A\n[body] B\n[cta] C")
    assert s.narration_text() == "A\nB\nC"


def test_split_captions_by_sentence_and_length():
    text = "완벽보다 완료가 이긴다. 지금 시작하라는 뜻입니다."
    caps = split_captions(text, max_chars=20)
    assert len(caps) == 2
    assert caps[0].startswith("완벽보다")


def test_split_captions_hard_split_long_korean():
    text = "가나다라마바사아자차카타파하가나다라마바사"  # 공백 없는 긴 한국어
    caps = split_captions(text, max_chars=8)
    assert all(len(c) <= 8 for c in caps)
    assert "".join(caps) == text


def test_split_captions_empty():
    assert split_captions("   ") == []


def test_caption_lines_splits_each_spoken_line():
    s = parse_script("[hook] 짧은 훅\n[body] 이것은 조금 더 긴 한 줄의 본문 문장입니다")
    caps = s.caption_lines(max_chars=10)
    assert all(len(c) <= 10 for c in caps)
    assert caps[0] == "짧은 훅"


def test_estimate_seconds_positive():
    assert estimate_seconds("가나다라마바사", chars_per_sec=7.0) > 0
