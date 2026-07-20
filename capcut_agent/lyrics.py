"""가사 자막: Whisper 받아쓰기 → SRT.

`transcribe()` 는 faster-whisper(또는 openai-whisper)로 노래에서 가사와
타임스탬프를 추출합니다. `segments_to_srt()` / `write_srt()` 는 순수 함수로
의존성 없이 테스트 가능합니다.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


@dataclass
class LyricSegment:
    """타임스탬프가 있는 가사 한 줄.

    Attributes:
        start/end: 초.
        text: 주 자막(보통 영어 원문).
        secondary: 보조 자막(예: 한글 번역). 이중 자막용, 없으면 None.
    """

    start: float  # 초
    end: float    # 초
    text: str
    secondary: Optional[str] = None

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"end({self.end}) < start({self.start}) 인 세그먼트가 있습니다.")


@dataclass
class WordTiming:
    """Whisper 가 준 단어 하나의 타이밍."""

    word: str
    start: float  # 초
    end: float    # 초


def _format_timestamp(seconds: float) -> str:
    """초 → SRT 타임코드 'HH:MM:SS,mmm'."""
    if seconds < 0:
        seconds = 0.0
    ms_total = int(round(seconds * 1000))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def segments_to_srt(segments: Sequence[LyricSegment]) -> str:
    """가사 세그먼트를 SRT 문자열로 변환 (순수 함수).

    빈 텍스트는 건너뛰고, 인덱스는 1부터 다시 매깁니다.
    """
    lines: List[str] = []
    idx = 1
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_format_timestamp(seg.start)} --> {_format_timestamp(seg.end)}")
        lines.append(text)
        lines.append("")  # 블록 구분 빈 줄
        idx += 1
    return "\n".join(lines) + ("\n" if lines else "")


def write_srt(segments: Sequence[LyricSegment], path: str) -> str:
    """SRT 파일로 저장하고 경로를 반환."""
    content = segments_to_srt(segments)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def clamp_segments_to_duration(
    segments: Sequence[LyricSegment], duration: float
) -> List[LyricSegment]:
    """세그먼트를 노래 길이 안으로 잘라내고, 겹침/역전을 정리."""
    cleaned: List[LyricSegment] = []
    prev_end = 0.0
    for seg in segments:
        start = max(0.0, min(seg.start, duration))
        end = max(start, min(seg.end, duration))
        if end <= start:
            continue
        # 직전 자막과 겹치면 시작을 밀어줌.
        start = max(start, prev_end)
        if end <= start:
            continue
        cleaned.append(LyricSegment(start=round(start, 3), end=round(end, 3),
                                    text=seg.text, secondary=seg.secondary))
        prev_end = end
    return cleaned


def transcribe(
    audio_path: str,
    *,
    model_size: str = "small",
    language: Optional[str] = None,
) -> List[LyricSegment]:
    """오디오에서 가사를 받아써 세그먼트 목록을 만듭니다.

    faster-whisper 를 우선 사용하고, 없으면 openai-whisper 로 폴백합니다.

    Args:
        audio_path: 노래 파일 경로.
        model_size: 모델 크기("tiny"~"large-v3"). 클수록 정확·느림.
        language: 언어 코드("ko"/"en"/...). None 이면 자동 감지.
    """
    try:
        return _transcribe_faster_whisper(audio_path, model_size, language)
    except ImportError:
        return _transcribe_openai_whisper(audio_path, model_size, language)


def _transcribe_faster_whisper(
    audio_path: str, model_size: str, language: Optional[str]
) -> List[LyricSegment]:
    from faster_whisper import WhisperModel  # noqa: WPS433

    # CPU 기본, GPU 있으면 device="cuda" 로 바꾸면 훨씬 빠름.
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _info = model.transcribe(
        audio_path,
        language=language,
        vad_filter=True,  # 무음 구간 제거로 자막 타이밍 개선
        word_timestamps=False,
    )
    return [
        LyricSegment(start=float(s.start), end=float(s.end), text=s.text.strip())
        for s in segments
        if s.text and s.text.strip()
    ]


def _transcribe_openai_whisper(
    audio_path: str, model_size: str, language: Optional[str]
) -> List[LyricSegment]:
    import whisper  # noqa: WPS433

    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, language=language, verbose=False)
    out: List[LyricSegment] = []
    for seg in result.get("segments", []):
        text = str(seg.get("text", "")).strip()
        if text:
            out.append(
                LyricSegment(
                    start=float(seg["start"]), end=float(seg["end"]), text=text
                )
            )
    return out


# =========================================================================
# 가사 교정 (정답 가사 + Whisper 타이밍 = 강제 정렬)
#
# Whisper 자동 자막은 노래(보컬+반주)에서 오탈자/오인식이 잦습니다. 정답 가사가
# 있으면 "텍스트는 정답, 타이밍은 Whisper" 로 합쳐 정확한 자막을 만듭니다.
# =========================================================================


def _normalize_word(word: str) -> str:
    """정렬용 단어 정규화: 소문자 + 알파벳/숫자만."""
    return re.sub(r"[^a-z0-9]", "", word.lower())


def transcribe_words(
    audio_path: str,
    *,
    model_size: str = "small",
    language: Optional[str] = None,
) -> List[WordTiming]:
    """단어 단위 타임스탬프로 받아씁니다(강제 정렬용).

    faster-whisper 우선, 없으면 openai-whisper 폴백.
    """
    try:
        from faster_whisper import WhisperModel  # noqa: WPS433

        model = WhisperModel(model_size, device="auto", compute_type="int8")
        segments, _info = model.transcribe(
            audio_path, language=language, vad_filter=True, word_timestamps=True
        )
        out: List[WordTiming] = []
        for seg in segments:
            for w in (getattr(seg, "words", None) or []):
                token = (w.word or "").strip()
                if token:
                    out.append(WordTiming(token, float(w.start), float(w.end)))
        return out
    except ImportError:
        import whisper  # noqa: WPS433

        model = whisper.load_model(model_size)
        result = model.transcribe(
            audio_path, language=language, word_timestamps=True, verbose=False
        )
        out = []
        for seg in result.get("segments", []):
            for w in seg.get("words", []):
                token = str(w.get("word", "")).strip()
                if token:
                    out.append(WordTiming(token, float(w["start"]), float(w["end"])))
        return out


def _distribute_lines(lines: Sequence[str], start: float, end: float) -> List[LyricSegment]:
    """가사 줄을 [start, end] 구간에 단어 수 비례로 균등 배치 (폴백)."""
    lines = [l for l in lines if l.strip()]
    if not lines:
        return []
    span = max(end - start, 0.001)
    weights = [max(len(l.split()), 1) for l in lines]
    total = sum(weights)
    out: List[LyricSegment] = []
    cursor = start
    for line, w in zip(lines, weights):
        dur = span * w / total
        out.append(LyricSegment(round(cursor, 3), round(cursor + dur, 3), line))
        cursor += dur
    return out


def _fill_missing_times(mids: List[Optional[float]], duration: float) -> List[float]:
    """None 인 지점을 이웃 사이 선형 보간(양끝은 외삽)으로 채웁니다."""
    n = len(mids)
    known = [i for i in range(n) if mids[i] is not None]
    if not known:
        return [duration * (i + 0.5) / n for i in range(n)]

    filled = list(mids)
    first = known[0]
    for i in range(first):  # 앞쪽 외삽
        filled[i] = filled[first] * (i + 1) / (first + 1)
    last = known[-1]
    for i in range(last + 1, n):  # 뒤쪽 외삽
        filled[i] = filled[last] + (duration - filled[last]) * (i - last) / (n - last)
    for a, b in zip(known, known[1:]):  # 중간 보간
        if b - a > 1:
            for i in range(a + 1, b):
                frac = (i - a) / (b - a)
                filled[i] = filled[a] + (filled[b] - filled[a]) * frac
    return [float(x) for x in filled]


def align_lyrics(
    official_lines: Sequence[str],
    *,
    whisper_words: Optional[Sequence[WordTiming]] = None,
    whisper_segments: Optional[Sequence[LyricSegment]] = None,
    duration: float = 0.0,
) -> List[LyricSegment]:
    """정답 가사에 Whisper 타이밍을 이식해 교정된 자막을 만듭니다 (순수 함수).

    difflib 로 (Whisper 단어열 ↔ 정답 단어열)을 정렬하고, 정답 각 단어에
    대응 Whisper 단어의 시각을 부여합니다. Whisper 에만 있는 단어(오인식)는
    버리고, 정답에만 있는 단어(누락)는 이웃 시각으로 보간합니다. 이렇게 하면
    자동 자막이 틀려도 **정답 가사가 올바른 타이밍에** 놓입니다.

    단어 타임스탬프가 없으면(whisper_segments 만 있을 때) 해당 구간에 정답
    줄을 단어 수 비례로 분배합니다.

    Args:
        official_lines: 정답 가사 줄(부를 수 있는 줄, 섹션 태그 제거된 상태).
        whisper_words: 단어 타임스탬프(권장 경로).
        whisper_segments: 세그먼트 타임스탬프(폴백).
        duration: 노래 길이(초). 보간/폴백 경계에 사용.

    Returns:
        교정된 LyricSegment 목록.
    """
    lines = [l.strip() for l in official_lines if l and l.strip()]
    if not lines:
        return []

    # 폴백: 단어 타임스탬프가 없으면 세그먼트 구간에 분배.
    if not whisper_words:
        if whisper_segments:
            start = min(s.start for s in whisper_segments)
            end = max(s.end for s in whisper_segments)
        else:
            start, end = 0.0, duration or (len(lines) * 3.0)
        return clamp_segments_to_duration(
            _distribute_lines(lines, start, end), duration or end
        )

    # 정답 단어 토큰 (line_idx, normalized)
    official_tokens: List[Tuple[int, str]] = []
    for li, line in enumerate(lines):
        for raw in line.split():
            norm = _normalize_word(raw)
            if norm:
                official_tokens.append((li, norm))
    if not official_tokens:
        return []

    w_norm = [_normalize_word(w.word) for w in whisper_words]
    o_norm = [t[1] for t in official_tokens]

    matcher = difflib.SequenceMatcher(None, w_norm, o_norm, autojunk=False)
    mids: List[Optional[float]] = [None] * len(official_tokens)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "replace"):
            wcount = i2 - i1
            ocount = j2 - j1
            for k in range(ocount):
                wi = i1 + min(int(k * wcount / max(ocount, 1)), wcount - 1)
                ww = whisper_words[wi]
                mids[j1 + k] = (ww.start + ww.end) / 2.0
        # insert(정답에만) → None 유지(보간), delete(Whisper에만) → 무시

    dur = duration or (whisper_words[-1].end if whisper_words else 0.0)
    mids_filled = _fill_missing_times(mids, dur)

    # 줄별 대표 시각(단어 시각의 최소)을 산출. mids 는 모두 채워졌으므로
    # 모든 줄이 존재합니다.
    line_start_raw = [None] * len(lines)  # type: List[Optional[float]]
    line_end_raw = [None] * len(lines)
    for (li, _), t in zip(official_tokens, mids_filled):
        if line_start_raw[li] is None or t < line_start_raw[li]:
            line_start_raw[li] = t
        if line_end_raw[li] is None or t > line_end_raw[li]:
            line_end_raw[li] = t

    return _finalize_aligned_lines(lines, line_start_raw, line_end_raw, dur)


def _finalize_aligned_lines(
    lines: Sequence[str],
    starts_raw: Sequence[Optional[float]],
    ends_raw: Sequence[Optional[float]],
    duration: float,
    *,
    min_dur: float = 0.4,
) -> List[LyricSegment]:
    """정렬 결과를 순서대로 정리합니다. 정답 가사는 한 줄도 버리지 않습니다.

    - 줄 순서(=실제 노래 순서)를 강제로 단조 증가로 만듭니다.
      (반복 후렴이 앞쪽으로 잘못 매칭돼도 뒤로 밀어 순서를 지킴)
    - 각 줄은 다음 줄 시작까지 표시(카라오케식, 빈틈 없음).
    """
    n = len(lines)
    if n == 0:
        return []
    # None(시각 미상)은 이웃 보간으로 채움.
    starts = _fill_missing_times(list(starts_raw), duration)

    # 단조 증가 강제
    for i in range(1, n):
        if starts[i] < starts[i - 1] + min_dur:
            starts[i] = starts[i - 1] + min_dur

    total = duration if duration > 0 else starts[-1] + min_dur
    segments: List[LyricSegment] = []
    for i in range(n):
        s = max(0.0, starts[i])
        if i + 1 < n:
            e = starts[i + 1]
        else:
            last_end = ends_raw[i] if ends_raw[i] is not None else s + min_dur
            e = max(last_end, s + min_dur)
        e = min(e, total) if total > 0 else e
        if e <= s:
            e = s + min_dur
        segments.append(LyricSegment(round(s, 3), round(e, 3), lines[i].strip()))
    return segments


def correct_lyrics(
    audio_path: str,
    official_lines: Sequence[str],
    *,
    model_size: str = "small",
    language: Optional[str] = None,
    duration: float = 0.0,
) -> List[LyricSegment]:
    """오디오에서 단어 타이밍을 받아쓴 뒤 정답 가사에 정렬(교정)합니다.

    단어 타임스탬프가 안 나오면 세그먼트 받아쓰기로 폴백해 분배합니다.
    """
    words = transcribe_words(audio_path, model_size=model_size, language=language)
    if words:
        return align_lyrics(official_lines, whisper_words=words, duration=duration)
    segments = transcribe(audio_path, model_size=model_size, language=language)
    return align_lyrics(official_lines, whisper_segments=segments, duration=duration)
