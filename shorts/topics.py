"""성공 동기부여 주제 뱅크 + 결정론적 로테이션.

"오늘 뭐 만들지?"를 자동화합니다. 주제 뱅크에서 결정론적으로(시드 기반) 뽑아
콘텐츠 캘린더를 만들 수 있습니다. `Math.random`/`Date.now` 없이 재현 가능합니다.

각 주제는 카테고리로 묶여 있어 채널 니치에 맞게 필터링할 수 있습니다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Topic:
    """동기부여 주제 하나. angle 은 훅으로 바로 쓸 수 있는 각도."""

    category: str
    title: str
    angle: str


# 카테고리별 주제. 채널 성장에 강한 "성공 마인드셋" 계열 중심.
TOPICS: List[Topic] = [
    # 새벽/루틴
    Topic("루틴", "성공한 사람들의 새벽 루틴", "당신이 늦잠 자는 동안 그들이 하는 것"),
    Topic("루틴", "하루를 지배하는 아침 5분", "아침 첫 5분이 하루 전체를 바꾼다"),
    Topic("루틴", "밤에 이걸 하면 인생이 바뀐다", "잠들기 전 3분이 내일의 나를 만든다"),
    # 마인드셋
    Topic("마인드셋", "가난한 마인드 vs 부자 마인드", "돈을 대하는 태도가 통장을 바꾼다"),
    Topic("마인드셋", "실패를 두려워하지 않는 법", "실패는 데이터일 뿐이다"),
    Topic("마인드셋", "남과 비교하는 순간 지는 이유", "비교의 대상은 어제의 나 하나뿐"),
    Topic("마인드셋", "핑계를 멈추는 한 문장", "핑계가 끝나는 곳에서 성장이 시작된다"),
    Topic("마인드셋", "완벽주의가 당신을 망치는 이유", "완벽보다 완료가 이긴다"),
    # 습관/실행
    Topic("실행", "작심삼일을 끝내는 법", "동기가 아니라 시스템이 이긴다"),
    Topic("실행", "미루는 습관을 부수는 2분 규칙", "2분만 시작하면 뇌가 속는다"),
    Topic("실행", "성장하는 사람의 1% 법칙", "매일 1%면 1년에 37배"),
    Topic("실행", "지금 당장 시작해야 하는 이유", "완벽한 타이밍은 오지 않는다"),
    # 돈/부
    Topic("부", "20대에 알았어야 할 돈의 진실", "시간은 가장 비싼 자산이다"),
    Topic("부", "부자가 되는 첫 번째 습관", "쓰기 전에 먼저 나에게 지불하라"),
    Topic("부", "돈이 따라오는 사람의 특징", "가치를 먼저 주는 사람에게 돈이 온다"),
    # 자기확신
    Topic("확신", "자존감을 끌어올리는 말", "나는 아직 성장 중이다"),
    Topic("확신", "불안을 이기는 법", "불안은 준비하라는 신호다"),
    Topic("확신", "포기하고 싶을 때 보는 영상", "여기서 멈추면 지금까지가 아깝다"),
    Topic("확신", "당신은 생각보다 강하다", "버텨낸 어제가 그 증거다"),
    # 시간/집중
    Topic("집중", "집중력을 되찾는 법", "산만함은 습관, 집중도 습관"),
    Topic("집중", "시간을 버는 사람들의 비밀", "우선순위가 곧 인생의 방향"),
    Topic("집중", "스마트폰에 시간을 뺏기지 않는 법", "알림을 끄는 순간 삶이 켜진다"),
]


def categories() -> List[str]:
    """등록된 카테고리 목록(정렬)."""
    return sorted({t.category for t in TOPICS})


def _seed_index(seed: str, modulo: int) -> int:
    """문자열 시드 → 안정적 인덱스(플랫폼/실행 간 재현). 해시 기반."""
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(h, 16) % max(1, modulo)


def pick_topics(
    n: int,
    *,
    seed: str = "seed",
    category: Optional[str] = None,
) -> List[Topic]:
    """주제 뱅크에서 겹치지 않게 n개를 결정론적으로 선택합니다.

    같은 (n, seed, category)면 항상 같은 결과 → 캘린더 재현 가능.
    """
    pool = [t for t in TOPICS if category is None or t.category == category]
    if not pool:
        return []
    n = max(0, min(n, len(pool)))
    # 시드로 시작 오프셋 + 스텝을 정해 균등하게 순회(중복 없이).
    start = _seed_index(seed, len(pool))
    step = 1 + _seed_index(seed + "step", max(1, len(pool) - 1))
    # step 과 len 이 서로소가 아니면 순회가 겹치므로 서로소가 될 때까지 보정.
    while _gcd(step, len(pool)) != 1:
        step += 1
    out: List[Topic] = []
    idx = start
    for _ in range(n):
        out.append(pool[idx % len(pool)])
        idx += step
    return out


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def daily_plan(
    days: int,
    *,
    per_day: int = 1,
    seed: str = "plan",
    category: Optional[str] = None,
) -> Dict[int, List[Topic]]:
    """며칠치 콘텐츠 캘린더(day 인덱스 → 주제들)를 만듭니다.

    각 날은 seed+day 로 독립적으로 뽑되 뱅크를 최대한 순환 사용합니다.
    """
    plan: Dict[int, List[Topic]] = {}
    for d in range(days):
        plan[d] = pick_topics(per_day, seed=f"{seed}:{d}", category=category)
    return plan
