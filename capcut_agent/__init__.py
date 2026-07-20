"""CapCut Auto-Edit Agent.

노래에 맞춰 소름돋는 화면 전환과 가사 자막을 자동으로 만들어
캡컷(CapCut / 剪映) 초안(draft) 프로젝트 파일로 출력하는 에이전트입니다.

파이프라인:
    오디오 → (비트/드롭 분석) ┐
                              ├→ 캡컷 draft 빌더 → draft_content.json
    오디오 → (Whisper 가사)  ┘

무거운 의존성(librosa / whisper / pyJianYingDraft)은 실제 실행 시에만
지연 임포트합니다. 순수 로직(비트 선정, SRT 생성, 프리셋)은 의존성 없이
동작하도록 분리되어 있습니다.
"""

from .config import AgentConfig, load_config

__all__ = ["AgentConfig", "load_config", "__version__"]

__version__ = "0.1.0"
