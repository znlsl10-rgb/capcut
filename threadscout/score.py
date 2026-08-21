"""지표 계산 + 백분위 가중합 스코어링.

절대 수치(좋아요 1만)는 계정 크기·주제·수집 시점에 따라 의미가 달라서,
**수집한 풀(pool) 안에서의 백분위**로 환산한 뒤 가중합합니다(0~100점).

기본 가중치(합 1.0)
  exposure     0.25  노출량        조회수(없으면 추정)
  share_rate   0.25  공유율        (리포스트+인용+공유) / 노출
  reply_rate   0.25  댓글율        댓글 / 노출
  reach        0.15  도달 배수     노출 / 팔로워  (작은 계정이 크게 터진 글)
  velocity     0.10  확산 속도     노출 / 경과시간

'노출 잘 되고 댓글·공유 많은 글' = exposure + share_rate + reply_rate 에 무게를 몰아둔 형태.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from .models import ThreadPost, hangul_ratio

# 조회수 미제공 액터용: 좋아요 → 노출 환산 기본 배수(풀에서 실측되면 그 값 사용)
DEFAULT_VIEWS_PER_LIKE = 40.0


@dataclass(frozen=True)
class ScoreWeights:
    exposure: float = 0.25
    share_rate: float = 0.25
    reply_rate: float = 0.25
    reach: float = 0.15
    velocity: float = 0.10

    def as_dict(self) -> Dict[str, float]:
        return {
            "exposure": self.exposure,
            "share_rate": self.share_rate,
            "reply_rate": self.reply_rate,
            "reach": self.reach,
            "velocity": self.velocity,
        }

    def normalized(self) -> "ScoreWeights":
        total = sum(self.as_dict().values())
        if total <= 0:
            return ScoreWeights()
        return ScoreWeights(**{k: v / total for k, v in self.as_dict().items()})


@dataclass(frozen=True)
class Filters:
    """수집 결과에서 분석 대상만 남기는 조건."""

    exclude_korean: bool = True        # 해외 글만 (한글 비중 높은 글 제외)
    hangul_max_ratio: float = 0.15
    languages: Sequence[str] = ()      # 비우면 전체 (예: ("en", "ja"))
    min_views: int = 0
    min_likes: int = 0
    min_replies: int = 0
    max_age_days: Optional[int] = None
    exclude_replies: bool = True       # 남의 글에 단 답글 제외
    exclude_reposts: bool = True
    exclude_ads: bool = True
    max_followers: Optional[int] = None  # 대형 계정 제외 (내가 따라할 수 있는 글만)


@dataclass
class ScoredPost:
    """ThreadPost + 계산된 지표/점수."""

    post: ThreadPost
    effective_views: float
    views_estimated: bool
    share_rate: float
    reply_rate: float
    engagement_rate: float
    reach_multiple: Optional[float]
    velocity: Optional[float]
    parts: Dict[str, float]          # 지표별 백분위(0~1)
    score: float                     # 0~100

    @property
    def url(self) -> str:
        return self.post.url

    def to_dict(self) -> Dict[str, object]:
        data = self.post.to_dict()
        data.update(
            {
                "score": round(self.score, 1),
                "effective_views": int(self.effective_views),
                "views_estimated": self.views_estimated,
                "share_rate_pct": round(self.share_rate * 100, 3),
                "reply_rate_pct": round(self.reply_rate * 100, 3),
                "engagement_rate_pct": round(self.engagement_rate * 100, 3),
                "reach_multiple": round(self.reach_multiple, 2) if self.reach_multiple else None,
                "views_per_hour": round(self.velocity, 1) if self.velocity else None,
                "score_parts": {k: round(v, 3) for k, v in self.parts.items()},
            }
        )
        return data


# --- 필터 ---------------------------------------------------------------
def apply_filters(posts: Sequence[ThreadPost], filters: Filters) -> List[ThreadPost]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=filters.max_age_days) if filters.max_age_days else None
    langs = {lang.lower() for lang in filters.languages}
    kept: List[ThreadPost] = []

    for post in posts:
        if filters.exclude_replies and post.is_reply:
            continue
        if filters.exclude_reposts and post.is_repost:
            continue
        if filters.exclude_ads and post.is_ad:
            continue
        if filters.exclude_korean and hangul_ratio(post.text) > filters.hangul_max_ratio:
            continue
        if langs and post.language.split("-")[0] not in langs:
            continue
        if (post.views or 0) < filters.min_views:
            continue
        if post.likes < filters.min_likes:
            continue
        if post.replies < filters.min_replies:
            continue
        if filters.max_followers is not None and (post.followers or 0) > filters.max_followers:
            continue
        if cutoff and post.created_at and post.created_at < cutoff:
            continue
        kept.append(post)
    return kept


# --- 백분위 ------------------------------------------------------------
def percentile_ranks(values: Sequence[Optional[float]]) -> List[float]:
    """값 목록 → 0~1 백분위. None 은 0.0(=최하위 취급).

    동점은 같은 값을 받고, 값이 하나뿐이면 모두 0.5.
    """
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    ranks = [0.0] * len(values)
    if not present:
        return ranks
    if len(present) == 1:
        ranks[present[0][0]] = 0.5
        return ranks

    ordered = sorted(present, key=lambda iv: iv[1])
    n = len(ordered)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        # 동점 구간의 평균 순위 → 0~1
        avg_rank = (i + j) / 2.0
        rank01 = avg_rank / (n - 1)
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = rank01
        i = j + 1
    return ranks


def estimate_views_per_like(posts: Sequence[ThreadPost]) -> float:
    """조회수를 주는 글들로부터 '좋아요 1개당 노출' 중앙값을 실측."""
    ratios = [
        post.views / max(post.likes, 1)
        for post in posts
        if post.views and post.views > 0 and post.likes >= 0
    ]
    if not ratios:
        return DEFAULT_VIEWS_PER_LIKE
    ratios.sort()
    mid = len(ratios) // 2
    median = ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2
    return max(median, 1.0)


def score_posts(
    posts: Sequence[ThreadPost],
    weights: Optional[ScoreWeights] = None,
) -> List[ScoredPost]:
    """게시물 목록 → 점수순(내림차순) ScoredPost 목록."""
    if not posts:
        return []
    weights = (weights or ScoreWeights()).normalized()
    vpl = estimate_views_per_like(posts)

    rows: List[ScoredPost] = []
    for post in posts:
        if post.views and post.views > 0:
            eff_views, estimated = float(post.views), False
        else:
            # 조회수 미제공 → 좋아요 기반 추정(최소 1로 0 나눗셈 방지)
            eff_views, estimated = max(post.likes * vpl, 1.0), True

        share_rate = post.spread / eff_views
        reply_rate = post.replies / eff_views
        eng_rate = post.engagement / eff_views
        reach = (eff_views / post.followers) if post.followers else None
        age = post.age_hours
        velocity = (eff_views / age) if age else None

        rows.append(
            ScoredPost(
                post=post,
                effective_views=eff_views,
                views_estimated=estimated,
                share_rate=share_rate,
                reply_rate=reply_rate,
                engagement_rate=eng_rate,
                reach_multiple=reach,
                velocity=velocity,
                parts={},
                score=0.0,
            )
        )

    # 노출/속도/도달은 편차가 커서 로그 스케일 후 백분위.
    part_values = {
        "exposure": [math.log10(r.effective_views + 10) for r in rows],
        "share_rate": [r.share_rate for r in rows],
        "reply_rate": [r.reply_rate for r in rows],
        "reach": [math.log10(r.reach_multiple + 0.01) if r.reach_multiple else None for r in rows],
        "velocity": [math.log10(r.velocity + 1) if r.velocity else None for r in rows],
    }
    ranked = {name: percentile_ranks(vals) for name, vals in part_values.items()}
    wd = weights.as_dict()

    scored: List[ScoredPost] = []
    for idx, row in enumerate(rows):
        parts = {name: ranked[name][idx] for name in ranked}
        total = sum(parts[name] * wd[name] for name in parts)
        scored.append(replace(row, parts=parts, score=round(total * 100, 2)))

    scored.sort(key=lambda r: r.score, reverse=True)
    return scored
