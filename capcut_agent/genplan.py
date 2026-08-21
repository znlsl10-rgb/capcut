"""AI 소재 "최소 제작" 계획.

힉스필드(또는 임의의 AI 영상 생성기)로 배경 소재를 만들 때, **몇 개를 만들면
곡을 채울 수 있는지**를 커버리지(슬로우 채움) 기준으로 계산합니다.

핵심 아이디어: 컷을 슬로우로 늘리면 짧은 클립 하나가 곡의 더 긴 구간을 덮습니다.
클립 하나가 덮는 곡 길이 = `clip_len / slow_floor` (예: 5s 클립을 0.5배로 늘리면
10s 를 덮음). 따라서 필요한 최소 클립 수 = `ceil(song / (clip_len/slow_floor))`.

`variety`(다양성 계수)로 최소보다 여유 있게 뽑아 몽타주가 반복돼 보이지 않게
할 수 있습니다. 모두 무거운 의존성 없이 동작하는 순수 로직입니다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict


@dataclass
class GenerationPlan:
    """AI 소재 생성 계획.

    Attributes:
        song_duration: 곡 길이(초).
        clip_len: 생성할 클립 1개 길이(초).
        slow_floor: 최대 슬로우(속도 하한). 0.5=최대 2배 느림.
        variety: 다양성 계수(1.0=최소, 1.5=50% 여유).
        coverage_per_clip: 클립 1개가 덮는 곡 길이(초).
        min_clips: 곡을 채우는 최소 클립 수(다양성 반영).
        raw_footage: 생성 원본 총 길이(초) = min_clips * clip_len.
        effective_speed: 실제 적용될 전역 속도(1.0=정상, <1=슬로우).
    """

    song_duration: float
    clip_len: float
    slow_floor: float
    variety: float
    coverage_per_clip: float
    min_clips: int
    raw_footage: float
    effective_speed: float

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


def min_clips_needed(
    song_duration: float,
    clip_len: float,
    slow_floor: float = 0.5,
    variety: float = 1.0,
) -> int:
    """곡을 채우는 데 필요한 최소 클립 수 (순수 함수).

    Args:
        song_duration: 곡 길이(초).
        clip_len: 생성할 클립 1개 길이(초).
        slow_floor: 최대 슬로우(0.1~1.0). 작을수록 더 느리게 늘려 적은 클립으로 채움.
        variety: 다양성 계수(>=1.0). 최소보다 여유 있게 뽑고 싶을 때.

    Returns:
        1 이상의 정수 클립 수.
    """
    if song_duration <= 0 or clip_len <= 0:
        return 1
    slow_floor = min(max(slow_floor, 0.1), 1.0)
    variety = max(variety, 1.0)
    coverage_per_clip = clip_len / slow_floor
    n = math.ceil(song_duration / coverage_per_clip * variety)
    return max(1, n)


def plan_generation(
    song_duration: float,
    clip_len: float = 5.0,
    slow_floor: float = 0.5,
    variety: float = 1.0,
) -> GenerationPlan:
    """생성 계획을 계산합니다(최소 클립 수 + 커버리지 정보).

    실제 초안 빌드 시의 전역 속도(`draft_builder.compute_global_speed`)와
    동일한 방식으로 effective_speed 를 계산해, "이만큼 만들면 이 속도로
    채워진다"를 미리 보여줍니다.
    """
    slow_floor = min(max(slow_floor, 0.1), 1.0)
    n = min_clips_needed(song_duration, clip_len, slow_floor, variety)
    raw = n * clip_len
    # compute_global_speed 와 동일한 규칙: ratio 클램프.
    if song_duration <= 0 or raw <= 0:
        speed = 1.0
    else:
        speed = max(slow_floor, min(1.0, raw / song_duration))
    return GenerationPlan(
        song_duration=round(song_duration, 3),
        clip_len=round(clip_len, 3),
        slow_floor=slow_floor,
        variety=round(variety, 3),
        coverage_per_clip=round(clip_len / slow_floor, 3),
        min_clips=n,
        raw_footage=round(raw, 3),
        effective_speed=round(speed, 3),
    )


def summarize_plan(plan: GenerationPlan) -> str:
    """사람이 읽는 생성 계획 요약."""
    slow_x = (1.0 / plan.effective_speed) if plan.effective_speed > 0 else 1.0
    return "\n".join([
        "🎬 AI 소재 최소 제작 계획",
        f"   곡 길이 {plan.song_duration:.1f}s · 클립 {plan.clip_len:.1f}s · "
        f"슬로우 한도 {plan.slow_floor:.2f}(최대 {1.0/plan.slow_floor:.1f}배)",
        f"   클립 1개가 {plan.coverage_per_clip:.1f}s 를 덮음 "
        f"→ 최소 {plan.min_clips}개 생성"
        + (f" (다양성 {plan.variety:.1f}x)" if plan.variety > 1.0 else ""),
        f"   원본 총 {plan.raw_footage:.1f}s → {plan.effective_speed:.2f}x 재생"
        f"({slow_x:.2f}배 슬로우)로 곡을 채움",
    ])
