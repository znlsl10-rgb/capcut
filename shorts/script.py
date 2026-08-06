"""대본 모델 — 훅 / 본문 / CTA + 쇼츠용 짧은 자막 분할.

동기부여 쇼츠는 **첫 3초 훅**과 **한눈에 읽히는 짧은 자막**이 생명입니다.
이 모듈은 무거운 의존성 없이(순수 로직) 대본을 다음으로 구조화합니다:

    - 훅(hook)   : 스크롤을 멈추게 하는 첫 문장
    - 본문(body) : 핵심 메시지 라인들(짧게 쪼갬)
    - CTA(cta)   : 구독/저장 유도 아웃트로

나레이션 음성에 강제정렬(capcut_agent.lyrics.correct_lyrics)할 "정답 텍스트"는
`narration_text()` 로 얻습니다. 자막으로 얹을 짧은 라인은 `caption_lines()` 입니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# 문장 종결(한국어/영어 공통) — 자막 분할 기준.
_SENT_END = re.compile(r"[.!?…。！？]+")
# 마커: [hook] / [본문] / [cta] 등 대괄호 라벨.
_MARKER = re.compile(r"^\s*[\[(<]\s*(hook|훅|body|본문|cta|아웃트로|outro)\s*[\])>]\s*", re.I)

_ROLE_ALIASES = {
    "hook": "hook", "훅": "hook",
    "body": "body", "본문": "body",
    "cta": "cta", "아웃트로": "cta", "outro": "cta",
}


@dataclass
class ScriptLine:
    """대본 한 줄. role 은 hook/body/cta."""

    text: str
    role: str = "body"


@dataclass
class MotivationScript:
    """구조화된 동기부여 쇼츠 대본.

    Attributes:
        topic: 이 영상의 주제(내부/메타용).
        lines: 순서대로의 ScriptLine 목록.
    """

    topic: str = ""
    lines: List[ScriptLine] = field(default_factory=list)

    # --- 조회 헬퍼 ---------------------------------------------------------
    def hook(self) -> str:
        for ln in self.lines:
            if ln.role == "hook":
                return ln.text
        return self.lines[0].text if self.lines else ""

    def body(self) -> List[str]:
        return [ln.text for ln in self.lines if ln.role == "body"]

    def cta(self) -> Optional[str]:
        for ln in reversed(self.lines):
            if ln.role == "cta":
                return ln.text
        return None

    def spoken_lines(self) -> List[str]:
        """나레이션으로 읽을 모든 라인(순서 유지)."""
        return [ln.text for ln in self.lines if ln.text.strip()]

    def narration_text(self) -> str:
        """나레이션 강제정렬용 정답 텍스트(줄바꿈 구분)."""
        return "\n".join(self.spoken_lines())

    def caption_lines(self, max_chars: int = 16) -> List[str]:
        """화면 자막용 짧은 라인들. 각 spoken 라인을 다시 쇼츠 크기로 분할."""
        out: List[str] = []
        for line in self.spoken_lines():
            out.extend(split_captions(line, max_chars=max_chars))
        return out

    def word_count(self) -> int:
        return sum(len(ln.text.replace(" ", "")) for ln in self.lines)


# --- 파싱 --------------------------------------------------------------------

def parse_script(raw: str, *, topic: str = "") -> MotivationScript:
    """자유 형식 대본 텍스트를 훅/본문/CTA 로 구조화합니다.

    규칙(관대하게):
      1) `[hook]`/`[본문]`/`[cta]` 마커가 있으면 그 라벨을 따릅니다(다음 마커 전까지).
      2) 마커가 없으면: 첫 유효 줄 = 훅, 마지막 유효 줄이 구독/저장/팔로우 유도면 CTA,
         나머지는 본문.
      3) 빈 줄은 무시. 각 줄은 그대로 한 라인이 됩니다(자막 분할은 caption_lines 에서).
    """
    lines: List[ScriptLine] = []
    current_role: Optional[str] = None

    raw_lines = [l.strip() for l in raw.splitlines()]
    # 마커 유무 판단
    has_markers = any(_MARKER.match(l) for l in raw_lines if l)

    for line in raw_lines:
        if not line:
            continue
        m = _MARKER.match(line)
        if m:
            current_role = _ROLE_ALIASES.get(m.group(1).lower(), "body")
            rest = _MARKER.sub("", line).strip()
            if rest:
                lines.append(ScriptLine(text=rest, role=current_role))
            continue
        role = current_role if (has_markers and current_role) else "body"
        lines.append(ScriptLine(text=line, role=role))

    if not has_markers and lines:
        # 휴리스틱: 첫 줄 훅, CTA 유도 문구면 cta.
        lines[0].role = "hook"
        if _looks_like_cta(lines[-1].text) and len(lines) > 1:
            lines[-1].role = "cta"

    return MotivationScript(topic=topic, lines=lines)


_CTA_HINTS = ("구독", "저장", "팔로우", "좋아요", "follow", "subscribe", "댓글", "공유")


def _looks_like_cta(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in _CTA_HINTS)


# --- 자막 분할 ---------------------------------------------------------------

def split_captions(text: str, *, max_chars: int = 16) -> List[str]:
    """긴 문장을 쇼츠 자막 크기의 짧은 라인들로 분할합니다(순수 함수).

    1) 문장 종결부호로 먼저 나눕니다.
    2) 여전히 긴 조각은 공백 기준으로 max_chars 근처에서 접습니다.
       (한국어처럼 공백이 적으면 글자 수 기준으로 강제 분할)
    """
    text = text.strip()
    if not text:
        return []

    # 1) 문장 단위
    pieces: List[str] = []
    last = 0
    for m in _SENT_END.finditer(text):
        seg = text[last:m.end()].strip()
        if seg:
            pieces.append(seg)
        last = m.end()
    tail = text[last:].strip()
    if tail:
        pieces.append(tail)
    if not pieces:
        pieces = [text]

    # 2) 길이 기준 접기
    out: List[str] = []
    for piece in pieces:
        out.extend(_wrap(piece, max_chars))
    return out


def _wrap(text: str, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    words = text.split(" ")
    if len(words) > 1:
        out: List[str] = []
        cur = ""
        for w in words:
            cand = (cur + " " + w).strip()
            if cur and len(cand) > max_chars:
                out.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            out.append(cur)
        # 접었는데도 한 조각이 너무 길면(공백 없는 한국어) 강제 분할.
        final: List[str] = []
        for seg in out:
            final.extend(_hard_split(seg, max_chars))
        return final
    return _hard_split(text, max_chars)


def _hard_split(text: str, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def estimate_seconds(text: str, *, chars_per_sec: float = 6.0) -> float:
    """나레이션 없이 대본 낭독 길이를 대략 추정(계획용).

    한국어 낭독 속도 대략 초당 5~7자. 훅 여백 포함 넉넉히 잡습니다.
    """
    chars = len(re.sub(r"\s+", "", text))
    return round(chars / max(1.0, chars_per_sec), 1)
