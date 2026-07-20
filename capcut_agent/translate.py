"""가사 번역 레이어 (영어 원문 → 한글 등 보조 자막).

이중 자막(영어 위 / 한글 아래)을 위해 각 가사 줄에 보조 언어 텍스트를 붙입니다.
한글 소스 우선순위:
  1) 직접 제공(줄 맞춤 텍스트 파일 / 리스트)  ← 가장 자연스러움
  2) 자동 번역(deep-translator, 온라인)         ← 없을 때 폴백

`attach_secondary` 는 순수 함수라 번역기 없이도 테스트됩니다.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from .lyrics import LyricSegment


def load_ko_lines(path: str) -> List[str]:
    """줄 맞춤 한글 가사 파일을 읽습니다(빈 줄 제거).

    영어 원문 줄 수와 같은 순서로 맞춰두면 1:1 매칭됩니다.
    """
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def attach_secondary(
    segments: Sequence[LyricSegment],
    secondary_lines: Sequence[str],
) -> List[LyricSegment]:
    """가사 세그먼트에 보조 텍스트를 순서대로 붙입니다 (순수 함수).

    세그먼트 수와 보조 줄 수가 다르면 짧은 쪽에 맞추고 나머지는 secondary=None.
    """
    out: List[LyricSegment] = []
    for i, seg in enumerate(segments):
        sec = secondary_lines[i].strip() if i < len(secondary_lines) and secondary_lines[i].strip() else None
        out.append(LyricSegment(start=seg.start, end=seg.end, text=seg.text, secondary=sec))
    return out


def translate_lines(
    lines: Sequence[str],
    *,
    source: str = "en",
    target: str = "ko",
    backend: str = "auto",
) -> List[str]:
    """가사 줄들을 번역합니다.

    backend:
      - "auto"/"deep-translator": deep-translator(GoogleTranslator) 사용(온라인).
      - 그 외: 지원하지 않음.

    Raises:
        RuntimeError: 번역 백엔드를 사용할 수 없을 때(설치/네트워크 안내).
    """
    if backend in ("auto", "deep-translator", "google"):
        return _translate_deep(list(lines), source=source, target=target)
    raise RuntimeError(f"지원하지 않는 번역 백엔드: {backend}")


def _translate_deep(lines: List[str], *, source: str, target: str) -> List[str]:
    try:
        from deep_translator import GoogleTranslator  # noqa: WPS433
    except ImportError as exc:  # noqa: BLE001
        raise RuntimeError(
            "자동 번역에는 deep-translator 가 필요합니다: pip install deep-translator\n"
            "또는 --lyrics-ko <한글파일> 로 직접 제공하세요(더 자연스러움)."
        ) from exc

    translator = GoogleTranslator(source=source, target=target)
    out: List[str] = []
    for line in lines:
        if not line.strip():
            out.append("")
            continue
        try:
            out.append(translator.translate(line) or "")
        except Exception as exc:  # noqa: BLE001 — 네트워크/속도 문제 시 원문 유지.
            out.append("")
    return out


def build_secondary(
    segments: Sequence[LyricSegment],
    *,
    ko_file: Optional[str] = None,
    auto_translate: bool = False,
    source: str = "en",
    target: str = "ko",
) -> List[LyricSegment]:
    """세그먼트에 보조(한글) 자막을 붙여 돌려줍니다.

    ko_file 이 있으면 그것을, 없고 auto_translate 면 자동 번역을 사용합니다.
    둘 다 없으면 원본 세그먼트를 그대로 반환(단일 자막).
    """
    if ko_file:
        return attach_secondary(segments, load_ko_lines(ko_file))
    if auto_translate:
        translated = translate_lines(
            [s.text for s in segments], source=source, target=target
        )
        return attach_secondary(segments, translated)
    return list(segments)
