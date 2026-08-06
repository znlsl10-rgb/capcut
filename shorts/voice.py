"""나레이션 음성 — 자동 생성(TTS) 시임.

동기부여 쇼츠의 목소리는 두 갈래로 넣을 수 있습니다:

1. **내 목소리 녹음** — 대본을 직접 읽어 mp3/m4a 로 저장, `--narration` 으로 전달.
   가장 자연스럽고 채널 정체성(페르소나)이 강하게 남습니다.

2. **TTS 자동 생성** — 대본 → 음성 자동 합성. 두 실행 맥락이 있습니다:
   - **이 에이전트 세션**: higgsfield MCP `generate_audio`(기본 seed_audio) 로 생성.
     한국어 프리셋 보이스는 `list_voices` 로 고른 뒤 voice_id 를 지정합니다.
   - **독립 실행 에이전트(내 서버/크론)**: MCP 가 없으므로 TTS 제공자의 REST API 를
     직접 호출합니다. API 키/시크릿은 **환경변수로만** 주입하고 절대 커밋하지 마세요.

이 모듈은 파이프라인이 나레이션을 얻는 "이음새"를 정의합니다. 실제 합성 호출은
제공자에 따라 다르므로, `NarrationRequest` 로 요청을 표준화하고 provider 콜러블을
꽂도록 했습니다. provider 없이 호출하면 명확한 안내와 함께 실패합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class NarrationRequest:
    """TTS 요청 표준형."""

    text: str                       # 낭독할 대본 전체(줄바꿈 포함 가능)
    out_path: str                   # 저장할 오디오 경로(mp3/m4a/wav)
    language: str = "ko"
    voice_id: Optional[str] = None  # 제공자 보이스 id(higgsfield 등)
    speed: float = 1.0              # 낭독 속도 배수


# provider(req) -> out_path 를 반환하는 콜러블.
NarrationProvider = Callable[[NarrationRequest], str]


def synthesize(req: NarrationRequest, provider: Optional[NarrationProvider] = None) -> str:
    """대본을 음성으로 합성합니다. provider 콜러블이 실제 TTS 를 수행합니다.

    provider 예(higgsfield REST 래퍼)를 꽂아 재사용하세요. provider 가 없으면
    무엇을 연결해야 하는지 안내와 함께 실패합니다.
    """
    if provider is None:
        raise NotImplementedError(
            "TTS provider 가 없습니다. 다음 중 하나를 연결하세요:\n"
            " · 이 에이전트 세션이라면 higgsfield MCP generate_audio 로 생성한 파일을 "
            "--narration 으로 전달\n"
            " · 독립 실행이라면 TTS REST API 래퍼를 provider 로 주입(키는 환경변수)\n"
            f"요청: '{req.text[:30]}…' → {req.out_path}"
        )
    return provider(req)
