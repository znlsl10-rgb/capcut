"""전환/애니메이션 스타일 프리셋.

각 전환·애니메이션은 pyJianYingDraft 의 enum 멤버 이름(중국어 원문)을
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
        transition_duration: 전환 길이(초).
        text_size: 자막 글자 크기(캡컷 상대 단위, 기본 5).
        text_color: 자막 색(#RRGGBB).
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
    text_size: float = 8.0
    text_color: str = "#FFFFFF"

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
# 멤버명은 pyJianYingDraft(剪映/CapCut) enum 원문(중국어)이며, 실제 앱에서
# 동일한 이름의 효과에 매핑됩니다.

PRESETS: Dict[str, StylePreset] = {
    # 소름돋는: 줌 펀치 + 드롭에 섬광/글리치. 강렬한 리듬 영상용 기본값.
    "goosebump": StylePreset(
        name="goosebump",
        description="소름돋는 스타일 — 비트마다 줌/블러 펀치, 드롭엔 섬광·글리치",
        transitions=["推近", "拉远", "快速缩放", "抖动放大", "模糊放大", "滑动放大"],
        strong_transitions=["闪白", "爆闪", "故障", "信号故障", "惊悚屏闪", "白光快闪"],
        bg_intro="动感放大",
        bg_strong_intro="抖动变焦",
        text_intro="弹入",
        text_strong_intro="放大震动",
        scene_effect="CCD闪光",
        transition_duration=0.4,
        text_size=9.0,
        text_color="#FFFFFF",
    ),
    # 강렬: EDM/힙합. 매 비트 컷 + 강한 줌/셰이크.
    "energetic": StylePreset(
        name="energetic",
        description="강렬한 스타일 — 빠른 컷과 셰이크, 리듬감 극대화",
        transitions=["快速缩放", "抖动放大", "抖动缩小", "运镜压缩", "震动缩小"],
        strong_transitions=["爆闪", "频闪", "快速震闪", "色差故障", "X形震闪"],
        bg_intro="动感放大",
        bg_strong_intro="震波",
        text_intro="随机弹跳",
        text_strong_intro="放大震动",
        scene_effect="心跳",
        transition_duration=0.33,
        text_size=9.0,
        text_color="#FFFFFF",
    ),
    # 잔잔: 발라드/감성. 부드러운 디졸브와 은은한 줌.
    "dreamy": StylePreset(
        name="dreamy",
        description="잔잔한 스타일 — 부드러운 디졸브와 은은한 줌, 감성 발라드용",
        transitions=["叠化", "溶解推进", "模糊放大", "滑动放大"],
        strong_transitions=["泛光", "星光叠化", "复古漏光", "炫光"],
        bg_intro="轻微放大",
        bg_strong_intro="放大",
        text_intro="渐显",
        text_strong_intro="波浪弹入",
        scene_effect="光晕",
        transition_duration=0.6,
        text_size=8.0,
        text_color="#FFFFFF",
    ),
    # 레트로: 필름/글리치 감성.
    "retro": StylePreset(
        name="retro",
        description="레트로 스타일 — 필름 감성과 글리치, VHS 무드",
        transitions=["复古放映", "胶片切闪", "复古漏光", "拉远"],
        strong_transitions=["电视故障_I", "信号故障", "雪花故障", "色块故障"],
        bg_intro="轻微抖动",
        bg_strong_intro="抖动变焦",
        text_intro="复古打字机",
        text_strong_intro="故障打字机",
        scene_effect="VCR",
        transition_duration=0.5,
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
