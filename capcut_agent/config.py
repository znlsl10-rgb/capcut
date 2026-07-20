"""에이전트 설정.

YAML 파일 또는 dict 로부터 설정을 읽어 검증합니다. 무거운 의존성 없이
동작하므로 단독으로 테스트 가능합니다.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class AgentConfig:
    """캡컷 자동 편집 에이전트 설정.

    배경 소재는 다음 세 가지 중 하나 이상으로 지정합니다(모두 지정 시 합쳐짐):
      - `background_path`   : 단일 파일
      - `background_paths`  : 여러 파일 목록
      - `background_dir`    : 폴더(안의 영상/이미지를 이름순으로 모두 사용)

    Attributes:
        audio_path: 노래 오디오 파일 경로 (mp3/wav/m4a 등).
        draft_folder: 캡컷 초안이 저장되는 루트 폴더.
            (예: Windows `%LOCALAPPDATA%/CapCut/User Data/Projects/com.lveditor.draft`)
        background_path: 단일 배경 영상/이미지 파일.
        background_paths: 여러 배경 클립 파일 목록.
        background_dir: 배경 클립들이 담긴 폴더.
        clip_order: 클립을 컷에 배치하는 순서. "sequential"(순환) 또는 "shuffle"(무작위).
        clip_seed: shuffle 재현용 시드.
        draft_name: 생성할 초안(프로젝트) 이름.
        width/height: 출력 해상도. 세로 숏폼 기본값(1080x1920).
        fps: 프레임레이트.
        style: 전환/자막 스타일 프리셋 이름 (transitions.PRESETS 참고).
        language: Whisper 받아쓰기 언어 힌트 (예: "ko", "en", None=자동).
        whisper_model: Whisper 모델 크기 ("tiny"/"base"/"small"/"medium"/"large-v3").
        min_transition_gap: 화면 전환 사이 최소 간격(초). 너무 잦은 컷 방지.
        max_transitions: 최대 전환 개수 상한 (0=무제한).
        beat_subdivision: 비트를 몇 개당 하나씩 전환에 사용할지(1=매 비트, 2=격박 등).
        emphasize_lyrics: True 면 가사가 나오는 구간의 비트를 강박으로 승격해
            그 구간의 화면 전환을 강렬하게 + 박자에 정확히 맞춥니다.
        lyrics_srt: 이미 준비된 SRT 경로. 지정 시 Whisper 대신 이 파일 사용.
        output_srt: 받아쓴 가사를 저장할 SRT 경로. 미지정 시 draft 옆에 생성.
    """

    audio_path: str
    draft_folder: str

    background_path: Optional[str] = None
    background_paths: List[str] = field(default_factory=list)
    background_dir: Optional[str] = None
    clip_order: str = "sequential"
    clip_seed: int = 0

    draft_name: str = "auto_lyric_video"

    width: int = 1080
    height: int = 1920
    fps: int = 30

    style: str = "goosebump"

    language: Optional[str] = None
    whisper_model: str = "small"

    min_transition_gap: float = 0.45
    max_transitions: int = 0
    beat_subdivision: int = 1
    emphasize_lyrics: bool = True

    lyrics_srt: Optional[str] = None
    output_srt: Optional[str] = None

    extra: Dict[str, Any] = field(default_factory=dict)

    _MEDIA_EXTS = (
        "mp4", "mov", "mkv", "webm", "avi", "m4v",  # 영상
        "jpg", "jpeg", "png", "gif", "webp", "bmp",  # 이미지
    )

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width/height 는 양수여야 합니다.")
        if self.fps <= 0:
            raise ValueError("fps 는 양수여야 합니다.")
        if self.min_transition_gap < 0:
            raise ValueError("min_transition_gap 은 0 이상이어야 합니다.")
        if self.beat_subdivision < 1:
            raise ValueError("beat_subdivision 은 1 이상이어야 합니다.")
        if self.clip_order not in ("sequential", "shuffle"):
            raise ValueError("clip_order 는 'sequential' 또는 'shuffle' 이어야 합니다.")
        if not (self.background_path or self.background_paths or self.background_dir):
            raise ValueError(
                "배경 소재가 없습니다. background_path / background_paths / background_dir "
                "중 하나 이상을 지정하세요."
            )

    def resolved_backgrounds(self) -> List[str]:
        """모든 소스를 합쳐 배경 클립 경로 목록을 만듭니다(중복 제거, 순서 유지).

        폴더는 이름순으로 정렬해 미디어 파일만 수집합니다.
        """
        paths: List[str] = []
        if self.background_dir:
            found: List[str] = []
            for ext in self._MEDIA_EXTS:
                found.extend(glob.glob(os.path.join(self.background_dir, f"*.{ext}")))
                found.extend(glob.glob(os.path.join(self.background_dir, f"*.{ext.upper()}")))
            paths.extend(sorted(found))
        paths.extend(self.background_paths)
        if self.background_path:
            paths.append(self.background_path)

        seen: set = set()
        ordered: List[str] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                ordered.append(p)
        return ordered

    def validate_paths(self) -> None:
        """실행 직전 파일 존재 여부를 검사합니다 (설정 로드 시점과 분리)."""
        if not os.path.isfile(self.audio_path):
            raise FileNotFoundError(f"오디오 파일을 찾을 수 없습니다: {self.audio_path}")
        backgrounds = self.resolved_backgrounds()
        if not backgrounds:
            raise FileNotFoundError("배경 클립을 하나도 찾지 못했습니다. 경로/폴더를 확인하세요.")
        for path in backgrounds:
            if not os.path.isfile(path):
                raise FileNotFoundError(f"배경 파일을 찾을 수 없습니다: {path}")
        if self.lyrics_srt and not os.path.isfile(self.lyrics_srt):
            raise FileNotFoundError(f"SRT 파일을 찾을 수 없습니다: {self.lyrics_srt}")

    def resolved_output_srt(self) -> str:
        """가사 SRT 저장 경로. 미지정 시 draft_name 기반 기본값."""
        if self.output_srt:
            return self.output_srt
        return f"{self.draft_name}.srt"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_KNOWN_FIELDS = set(AgentConfig.__dataclass_fields__.keys()) - {"extra"}


def from_dict(data: Dict[str, Any]) -> AgentConfig:
    """dict 로부터 AgentConfig 생성. 알 수 없는 키는 extra 로 보관."""
    known = {k: v for k, v in data.items() if k in _KNOWN_FIELDS}
    extra = {k: v for k, v in data.items() if k not in _KNOWN_FIELDS}
    missing = [k for k in ("audio_path", "draft_folder") if k not in known]
    if missing:
        raise ValueError(f"필수 설정 항목 누락: {', '.join(missing)}")
    if not any(k in known for k in ("background_path", "background_paths", "background_dir")):
        raise ValueError(
            "배경 소재 항목 누락: background_path / background_paths / background_dir 중 하나 필요"
        )
    if extra:
        known["extra"] = extra
    return AgentConfig(**known)


def load_config(path: str) -> AgentConfig:
    """YAML 설정 파일을 읽어 AgentConfig 로 변환."""
    import yaml  # 지연 임포트

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("설정 파일의 최상위는 매핑(dict)이어야 합니다.")
    return from_dict(data)
