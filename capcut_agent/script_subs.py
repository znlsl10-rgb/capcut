"""대본(스크립트) → 타임드 자막.

내 **대본 텍스트**를 자막으로 얹기 위한 모듈입니다. 대본을 줄 단위 캡션으로
정리하고(긴 문장은 적당히 분할), 영상 길이에 맞춰 시각을 배분합니다. 음악
비트가 주어지면 **비트에 맞춰** 캡션 경계를 놓아 "박자에 맞는" 자막이 됩니다.

모두 순수 로직으로 의존성 없이 테스트 가능합니다. 반환 타입은 기존 자막
파이프라인과 동일한 `LyricSegment` 입니다.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence

from .lyrics import LyricSegment


def parse_script(text: str, *, max_len: int = 42) -> List[str]:
    """대본 원문을 자막 줄 목록으로 정리 (순수 함수).

    - 빈 줄/공백 정리, 줄 단위로 우선 분할.
    - 한 줄이 너무 길면(max_len 초과) 문장부호/공백 기준으로 쪼갬.
    - 타임코드(SRT식 `00:00,000 --> ...`)나 순번만 있는 줄은 제외.
    """
    lines: List[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if "-->" in s:            # SRT 타임라인 줄 제외
            continue
        if re.fullmatch(r"\d+", s):  # SRT 순번 제외
            continue
        lines.extend(_split_long(s, max_len))
    return lines


def _split_long(s: str, max_len: int) -> List[str]:
    """긴 줄을 문장/구두점/공백 기준으로 max_len 이하로 분할."""
    if len(s) <= max_len:
        return [s]
    # 문장 종결부호 우선 분할.
    parts = re.split(r"(?<=[.!?。!?…])\s+", s)
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_len:
            out.append(p)
        else:
            out.extend(_wrap_words(p, max_len))
    return out


def _wrap_words(s: str, max_len: int) -> List[str]:
    """공백 기준 워드랩(그래도 길면 그대로)."""
    words = s.split()
    out: List[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_len:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out or [s]


def distribute_lines(
    lines: Sequence[str],
    duration: float,
    *,
    beats: Optional[Sequence[float]] = None,
    start_at: float = 0.0,
    min_dur: float = 0.8,
    gap: float = 0.05,
) -> List[LyricSegment]:
    """캡션 줄들을 영상 길이에 맞춰 시각 배분 (순수 함수).

    beats 가 주어지면 각 캡션의 시작을 비트에 맞춰(균등 인덱스) 스냅하고,
    없으면 남은 길이를 균등 분할합니다.

    Args:
        lines: 자막 줄 목록.
        duration: 전체 길이(초).
        beats: (선택) 비트 시각 목록. 있으면 박자에 맞춰 배치.
        start_at: 첫 자막 시작 시각(초).
        min_dur: 캡션 최소 노출 시간(초).
        gap: 캡션 사이 간격(초).
    """
    n = len(lines)
    if n == 0 or duration <= 0:
        return []

    if beats:
        bounds = _beat_bounds(beats, n, duration, start_at)
    else:
        span = max(0.0, duration - start_at)
        step = span / n
        bounds = [round(start_at + i * step, 3) for i in range(n)] + [round(duration, 3)]

    segments: List[LyricSegment] = []
    for i, line in enumerate(lines):
        s = bounds[i]
        e = bounds[i + 1] - gap
        if e - s < min_dur:
            e = min(duration, s + min_dur)
        if e <= s:
            e = min(duration, s + min_dur)
        segments.append(LyricSegment(start=round(s, 3), end=round(e, 3), text=line))
    return segments


def _beat_bounds(
    beats: Sequence[float], n: int, duration: float, start_at: float
) -> List[float]:
    """n 개 캡션의 경계를, start_at 이후의 비트들에 균등 인덱스로 스냅."""
    usable = [b for b in beats if b >= start_at]
    if len(usable) < 2:
        step = max(0.0, duration - start_at) / n
        return [round(start_at + i * step, 3) for i in range(n)] + [round(duration, 3)]
    # 비트를 n 구간으로 나눠 경계 비트를 고름.
    bounds: List[float] = []
    for i in range(n):
        idx = round(i * (len(usable) - 1) / n)
        bounds.append(round(usable[idx], 3))
    bounds.append(round(duration, 3))
    # 단조 증가 보정.
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = min(duration, bounds[i - 1] + 0.5)
    return bounds


def script_to_segments(
    text: str,
    duration: float,
    *,
    beats: Optional[Sequence[float]] = None,
    max_len: int = 42,
    start_at: float = 0.0,
) -> List[LyricSegment]:
    """대본 원문 → 타임드 자막(LyricSegment) 한 번에.

    parse_script + distribute_lines 를 묶은 편의 함수.
    """
    lines = parse_script(text, max_len=max_len)
    return distribute_lines(lines, duration, beats=beats, start_at=start_at)
