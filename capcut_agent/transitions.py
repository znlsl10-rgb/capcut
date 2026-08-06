"""전환/애니메이션 스타일 프리셋.

각 전환·애니메이션은 pyCapCut 의 enum 멤버 이름(CapCut 글로벌 영어 효과명)을
문자열로 보관합니다. 실제 enum 해석은 draft_builder 에서 `getattr` 로 처리하며,
이 모듈은 의존성 없이 "무엇을 언제 쓸지"만 결정하므로 테스트 가능합니다.

드롭/강박(strong) 구간에는 더 강렬한 전환(섬광·글리치·줌펀치)을 배치해
"소름돋는 화면 전환" 느낌을 만듭니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class StylePreset:
    """하나의 편집 스타일 정의.

    Attributes:
        name: 프리셋 이름.
        description: 사람이 읽는 설명.
        transitions: 일반 비트 전환 후보(순환 사용, TransitionType 멤버명).
        strong_transitions: 강박/드롭 전환 후보(순환 사용).
        bg_intro: 배경 세그먼트 입장 애니(IntroType 멤버명). None 가능.
        bg_strong_intro: 강박 세그먼트 입장 애니. None 가능.
        text_intro: 자막 입장 애니(TextIntro 멤버명).
        text_strong_intro: 강박 구간 자막 입장 애니. None 가능.
        scene_effect: 드롭에 얹는 화면 효과(VideoSceneEffectType 멤버명). None 가능.
        transition_duration: 일반 전환 길이(초).
        strong_transition_duration: 드롭/강박 전환 길이(초). 짧게 두면 컷이
            비트에 더 타이트하게 꽂혀 타격감이 커집니다.
        text_size: 자막 글자 크기(캡컷 상대 단위, 기본 5).
        text_color: 주 자막(영어 원문) 색(#RRGGBB).
        secondary_color: 보조 자막(한글 번역) 색. 이중 자막용.
    """

    name: str
    description: str
    transitions: List[str]
    strong_transitions: List[str]
    text_intro: str
    bg_intro: Optional[str] = None
    bg_strong_intro: Optional[str] = None
    text_strong_intro: Optional[str] = None
    scene_effect: Optional[str] = None
    transition_duration: float = 0.5
    strong_transition_duration: float = 0.2
    text_size: float = 8.0
    text_color: str = "#FFFFFF"
    secondary_color: str = "#FFE39A"  # 한글 번역: 부드러운 웜톤

    def transition_duration_for(self, strong: bool) -> float:
        """강박 여부에 따른 전환 길이(초)."""
        return self.strong_transition_duration if strong else self.transition_duration

    def pick_transition(self, index: int, strong: bool) -> Optional[str]:
        """index 번째 전환 이름을 고릅니다(순환). strong 이면 강렬 전환군 사용."""
        pool = self.strong_transitions if strong else self.transitions
        if not pool:
            pool = self.transitions or self.strong_transitions
        if not pool:
            return None
        return pool[index % len(pool)]

    def pick_bg_intro(self, strong: bool) -> Optional[str]:
        if strong and self.bg_strong_intro:
            return self.bg_strong_intro
        return self.bg_intro

    def pick_text_intro(self, strong: bool) -> str:
        if strong and self.text_strong_intro:
            return self.text_strong_intro
        return self.text_intro


# 프리셋 정의 -----------------------------------------------------------------
# 멤버명은 pyCapCut enum(CapCut 글로벌 영어 효과명)이며, 실제 CapCut 앱의
# 동일 효과에 매핑됩니다.

PRESETS: Dict[str, StylePreset] = {
    # 소름돋는: 줌 펀치 + 드롭에 섬광/글리치. 강렬한 리듬 영상용 기본값.
    "goosebump": StylePreset(
        name="goosebump",
        description="소름돋는 스타일 — 비트마다 줌/블러 펀치, 드롭엔 섬광·글리치",
        transitions=["Snap_Zoom", "Zoom_Transition", "Zoom_to_Change", "Flip_Zoom",
                     "Push_Away_2", "Zoom_Shake_2"],
        strong_transitions=["White_Flash", "Flash", "Signal_Glitch_2", "Subject_Flash",
                            "Lumin_Flash", "TV_Flickers"],
        bg_intro="Focus",
        bg_strong_intro="Skew_Shake",
        text_intro="Click",
        text_strong_intro="Bumper_Car",
        scene_effect="CCD",
        transition_duration=0.4,
        strong_transition_duration=0.18,  # 드롭 섬광은 짧고 강하게 → 비트에 타이트
        text_size=9.0,
        text_color="#FFFFFF",
    ),
    # 강렬: EDM/힙합. 매 비트 컷 + 강한 줌/셰이크.
    "energetic": StylePreset(
        name="energetic",
        description="강렬한 스타일 — 빠른 컷과 셰이크, 리듬감 극대화",
        transitions=["Snap_Zoom", "Zoom_Shake_2", "Bump", "Jerky_Camera", "Shake_down"],
        strong_transitions=["Flash", "White_Flash", "Subject_Flash", "Signal_Glitch_2",
                            "Dazzle_Pulse"],
        bg_intro="Skew_Shake",
        bg_strong_intro="Crisscross_Shake",
        text_intro="Bumper_Car",
        text_strong_intro="Click",
        scene_effect="Camera_Beats",
        transition_duration=0.33,
        strong_transition_duration=0.15,  # 가장 짧은 컷 타격
        text_size=9.0,
        text_color="#FFFFFF",
    ),
    # 잔잔: 발라드/감성. 부드러운 디졸브와 은은한 줌.
    "dreamy": StylePreset(
        name="dreamy",
        description="잔잔한 스타일 — 부드러운 디졸브와 은은한 줌, 감성 발라드용",
        transitions=["Dreamy_Bubbles", "Light_Leaks", "Elastic_Glowing", "Fold_Over"],
        strong_transitions=["Lumin_Flash", "Hot_Shimmers", "Film_Burn", "Light_Leaks"],
        bg_intro="Focus",
        bg_strong_intro="Chroma_Wave",
        text_intro="Golden_Dust",
        text_strong_intro="Wiping_In",
        scene_effect="Dreamy_Halo",
        transition_duration=0.6,
        strong_transition_duration=0.45,  # 감성 유지 위해 비교적 길게
        text_size=8.0,
        text_color="#FFFFFF",
    ),
    # 동기부여 쇼츠: 굵고 잘 읽히는 자막 + 깔끔하고 단단한 컷. 화려함보다
    # 메시지 전달력 우선. 문장 전환마다 임팩트 있는 줌, 핵심 구간엔 섬광.
    "motivation": StylePreset(
        name="motivation",
        description="동기부여 쇼츠 — 굵은 자막 + 단단한 줌컷, 핵심 문장에 임팩트",
        transitions=["Zoom_to_Change", "Snap_Zoom", "Push_Away_2", "Pull_In"],
        strong_transitions=["White_Flash", "Subject_Flash", "Lumin_Flash", "Flash"],
        bg_intro="Focus",
        bg_strong_intro="Snap_Zoom",
        text_intro="Bumper_Car",
        text_strong_intro="Click",
        scene_effect="Bling",
        transition_duration=0.32,
        strong_transition_duration=0.16,
        text_size=11.0,          # 쇼츠 굵고 크게(한눈에)
        text_color="#FFFFFF",
        secondary_color="#FFD24A",  # 강조 워드 웜 옐로
    ),
    # 시네마틱 동기부여: 잔잔하고 웅장한 무드. 나레이션 중심 명언/스토리.
    "cinematic": StylePreset(
        name="cinematic",
        description="시네마틱 동기부여 — 은은한 줌/디졸브, 명언·스토리 나레이션용",
        transitions=["Fade", "Dreamy_Bubbles", "Light_Leaks", "Pull_In"],
        strong_transitions=["Lumin_Flash", "Film_Burn", "Light_Leaks", "Hot_Shimmers"],
        bg_intro="Focus",
        bg_strong_intro="Chroma_Wave",
        text_intro="Wiping_In",
        text_strong_intro="Golden_Dust",
        scene_effect="Dreamy_Halo",
        transition_duration=0.6,
        strong_transition_duration=0.4,
        text_size=10.0,
        text_color="#FFFFFF",
        secondary_color="#FFD24A",
    ),
    # 레트로: 필름/글리치 감성.
    "retro": StylePreset(
        name="retro",
        description="레트로 스타일 — 필름 감성과 글리치, VHS 무드",
        transitions=["Film_Burn", "Dirty_Frame", "Light_Leaks", "TV_Flickers"],
        strong_transitions=["TV_Flickers", "Signal_Glitch_2", "Dirty_Frame", "Film_Burn"],
        bg_intro="TV_On",
        bg_strong_intro="Skew_Shake",
        text_intro="Slanted_Expand",
        text_strong_intro="Golden_Dust",
        scene_effect="VCR",
        transition_duration=0.5,
        strong_transition_duration=0.22,
        text_size=8.0,
        text_color="#FFE9A8",
    ),
}

DEFAULT_PRESET = "goosebump"


def get_preset(name: Optional[str]) -> StylePreset:
    """이름으로 프리셋을 가져옵니다. 없으면 사용 가능 목록과 함께 오류."""
    key = (name or DEFAULT_PRESET).strip()
    if key not in PRESETS:
        available = ", ".join(sorted(PRESETS))
        raise KeyError(f"알 수 없는 스타일 '{name}'. 사용 가능: {available}")
    return PRESETS[key]


def list_presets() -> List[str]:
    return sorted(PRESETS)
