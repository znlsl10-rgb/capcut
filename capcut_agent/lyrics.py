"""가사 자막: Whisper 받아쓰기 → SRT.

`transcribe()` 는 faster-whisper(또는 openai-whisper)로 노래에서 가사와
타임스탬프를 추출합니다. `segments_to_srt()` / `write_srt()` 는 순수 함수로
의존성 없이 테스트 가능합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass
class LyricSegment:
    """타임스탬프가 있는 가사 한 줄."""

    start: float  # 초
    end: float    # 초
    text: str

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"end({self.end}) < start({self.start}) 인 세그먼트가 있습니다.")


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
        cleaned.append(LyricSegment(start=round(start, 3), end=round(end, 3), text=seg.text))
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
