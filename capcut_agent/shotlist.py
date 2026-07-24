"""통일감 있는 다양한 클립을 위한 "촬영 리스트(shot recipe)".

**기준 이미지 1장**을 주면, 그 이미지의 스타일·분위기·화질을 그대로 유지한 채
서로 다른 앵글의 클립을 여러 개 만들기 위한 프롬프트 세트를 생성합니다.

사용자 지정 조건을 코드로 못박아, 매 생성마다 자동 반영됩니다:
  - **중간중간 1인칭 시점** (POV) 을 섞는다.
  - 1인칭은 **자연스러운 손떨림**(handheld shake) 을 넣는다.
  - 피사체가 **차량**이면 **운전자 1인칭 시점**을 반드시 포함한다.
  - 모든 컷은 **기준 이미지와 동일한 스타일·분위기·화질**로 통일한다.

실제 영상 생성(힉스필드 등)은 외부에서 하고, 이 모듈은 "무엇을 어떤 순서로
찍을지"만 정하므로 의존성 없이 테스트 가능합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ShotSpec:
    """한 컷의 정의.

    Attributes:
        name: 컷 이름(라벨).
        motion: 카메라 움직임/구도 프롬프트(영문, 생성기에 전달).
        pov: 1인칭 시점 컷인지(손떨림 문구가 붙습니다).
        vehicle_only: 차량 피사체일 때만 쓰는 컷인지(예: 운전자 시점).
    """

    name: str
    motion: str
    pov: bool = False
    vehicle_only: bool = False


# 기준 이미지와 스타일/화질을 통일하기 위해 모든 프롬프트에 붙는 접미사.
CONSISTENCY_SUFFIX = (
    "Match the exact style, mood, lighting, color grade and image quality of the "
    "reference image. Same subject and same environment, consistent cinematic look."
)

# 1인칭 손떨림 문구(자연스러운 흔들림).
HANDHELD = (
    "first-person POV, handheld camera at eye level with natural subtle shake as if "
    "walking, immersive and realistic motion"
)

# 촬영 라이브러리 — cinematic(3인칭)과 POV(1인칭)를 섞고, 차량 전용 컷 포함.
SHOT_LIBRARY: List[ShotSpec] = [
    ShotSpec("establishing", "Slow cinematic establishing shot revealing the whole subject and its surroundings, smooth camera push-in, shallow depth of field."),
    ShotSpec("orbit", "Slow orbit around the subject, reflections and light sweeping across surfaces, cinematic parallax."),
    ShotSpec("low_angle_track", "Low-angle tracking shot gliding alongside the subject, background lights streaking past, cinematic motion blur."),
    ShotSpec("detail_closeup", "Extreme close-up detail with a slow push, textures and highlights, soft bokeh background, shallow depth of field."),
    ShotSpec("pov_approach", f"{HANDHELD}, slowly walking toward the subject, breathing camera movement, immersive.", pov=True),
    ShotSpec("pov_around", f"{HANDHELD}, moving around and looking over the subject, head-turn motion, natural sway.", pov=True),
    ShotSpec("driver_pov", "First-person driver's POV from inside the car, hands on the steering wheel, glowing dashboard, city lights and neon streaking past through the windshield, natural handheld motion, immersive.", pov=True, vehicle_only=True),
    ShotSpec("crane_up", "Camera slowly cranes upward revealing the subject and the wider scene behind it, epic cinematic reveal."),
]


def build_shots(
    subject: str,
    *,
    is_vehicle: bool = False,
    count: int = 5,
    min_pov: int = 1,
) -> List[Dict[str, str]]:
    """기준 이미지로 만들 다양한 컷의 프롬프트 세트를 만듭니다 (순수 함수).

    보장 사항:
      - 피사체가 차량이면 **운전자 1인칭 시점**을 반드시 포함(1순위).
      - 최소 `min_pov` 개의 1인칭(POV) 컷을 포함(손떨림 문구 포함).
      - 나머지는 다양한 cinematic 컷으로 채우되 순서를 섞어 반복감을 줄임.
      - 모든 프롬프트에 통일감 접미사(CONSISTENCY_SUFFIX)를 붙임.

    Args:
        subject: 피사체 설명(예: "matte black sports car in a neon city at night").
        is_vehicle: 차량 여부(운전자 시점 컷 포함 조건).
        count: 만들 컷 개수(>=1).
        min_pov: 최소 1인칭 컷 수.

    Returns:
        [{"name": ..., "prompt": ...}, ...] 길이 count.
    """
    if count < 1:
        return []

    pool = [s for s in SHOT_LIBRARY if is_vehicle or not s.vehicle_only]

    selected: List[ShotSpec] = []
    used: set = set()

    def take(spec: ShotSpec) -> None:
        if spec.name not in used:
            selected.append(spec)
            used.add(spec.name)

    # 1) 차량이면 운전자 시점 먼저 확보.
    if is_vehicle:
        for s in pool:
            if s.vehicle_only:
                take(s)
                break

    # 2) 최소 POV 개수 확보.
    pov_shots = [s for s in pool if s.pov and not s.vehicle_only]
    i = 0
    while sum(1 for s in selected if s.pov) < min_pov and i < len(pov_shots):
        take(pov_shots[i])
        i += 1

    # 3) 나머지는 cinematic(비POV) → 남은 POV 순으로 다양하게 채움.
    fillers = [s for s in pool if not s.pov] + [s for s in pool if s.pov]
    i = 0
    while len(selected) < count and i < len(fillers):
        take(fillers[i])
        i += 1

    # 4) 그래도 모자라면(요청 개수가 라이브러리보다 많으면) 순환하며 변주.
    j = 0
    while len(selected) < count:
        base = pool[j % len(pool)]
        selected.append(base)
        j += 1

    selected = selected[:count]

    # 5) 순서를 살짝 섞어 establishing → 다양 → 마무리 느낌(결정적, 시드 불필요).
    ordered = _interleave(selected)

    out: List[Dict[str, str]] = []
    for idx, spec in enumerate(ordered):
        prompt = f"{spec.motion} Subject: {subject}. {CONSISTENCY_SUFFIX}"
        out.append({"name": f"{idx + 1:02d}_{spec.name}", "prompt": prompt})
    return out


def _interleave(specs: List[ShotSpec]) -> List[ShotSpec]:
    """POV 컷이 몰리지 않도록 cinematic/POV 를 번갈아 배치(결정적)."""
    cinematic = [s for s in specs if not s.pov]
    pov = [s for s in specs if s.pov]
    out: List[ShotSpec] = []
    ci = pi = 0
    # cinematic 로 시작해 번갈아.
    while ci < len(cinematic) or pi < len(pov):
        if ci < len(cinematic):
            out.append(cinematic[ci]); ci += 1
        if pi < len(pov):
            out.append(pov[pi]); pi += 1
    return out


def summarize_shots(shots: List[Dict[str, str]]) -> str:
    """사람이 읽는 촬영 리스트 요약."""
    lines = [f"🎥 촬영 리스트 — {len(shots)}컷 (기준 이미지로 스타일 통일)"]
    for s in shots:
        tag = "👁 1인칭" if "pov" in s["name"] or "driver" in s["name"] else "🎬 시네마틱"
        lines.append(f"   {s['name']}  {tag}")
    return "\n".join(lines)
