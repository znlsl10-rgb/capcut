"""게시 메타데이터 — 유튜브/틱톡 제목·설명·해시태그·검색 태그.

대본(MotivationScript) + 채널 프로필(ChannelProfile) 로부터 각 플랫폼에 맞는
게시 메타데이터를 순수 로직으로 생성합니다. 무거운 의존성 없이 테스트됩니다.

쇼츠 성장 관점 규칙:
  - 제목은 훅 기반으로 짧고 강하게. 유튜브 쇼츠는 `#Shorts` 를 포함.
  - 설명 첫 줄은 훅(검색/추천 반영), 본문 요약, CTA, 해시태그, 채널 서명 순.
  - 해시태그는 채널 공통 + 주제 키워드. 유튜브는 3~5개로 절제.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .channel import ChannelProfile, _dedup_hashtags
from .script import MotivationScript

_YOUTUBE_TITLE_MAX = 90   # 유튜브 제목 하드 리밋 100, 쇼츠는 짧을수록 유리
_SHORT_TITLE_TARGET = 40  # 쇼츠 권장(모바일에서 잘리지 않게)


@dataclass
class PublishMetadata:
    """한 영상의 게시 메타데이터."""

    platform: str
    title: str
    description: str
    hashtags: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)  # 유튜브 검색 태그(설명과 별개)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".。")


def _title_from_hook(hook: str, niche: str) -> str:
    """훅을 제목으로. 너무 짧으면 니치 키워드를 붙여 맥락 보강."""
    title = _clean(hook)
    if len(title) < 8 and niche:
        title = f"{title} | {niche}"
    if len(title) > _YOUTUBE_TITLE_MAX:
        title = title[: _YOUTUBE_TITLE_MAX - 1].rstrip() + "…"
    return title


def _topic_hashtags(topic: str) -> List[str]:
    """주제 문자열에서 해시태그 후보를 뽑습니다(2자 이상 토큰)."""
    tokens = re.split(r"[\s/·,]+", topic)
    tags: List[str] = []
    for tok in tokens:
        tok = re.sub(r"[^0-9A-Za-z가-힣]", "", tok)
        if len(tok) >= 2:
            tags.append("#" + tok)
    return tags


def build_metadata(
    script: MotivationScript,
    channel: ChannelProfile,
    *,
    platform: str = "youtube",
    max_hashtags: int = 5,
) -> PublishMetadata:
    """대본+채널로부터 플랫폼 메타데이터를 생성합니다.

    Args:
        platform: "youtube" 또는 "tiktok".
        max_hashtags: 설명/캡션에 넣을 해시태그 최대 개수.
    """
    hook = script.hook()
    niche = channel.niche

    title = _title_from_hook(hook, niche)

    # 해시태그: 플랫폼 필수 태그를 먼저(잘리지 않게) → 주제 키워드 → 채널 공통.
    platform_tags: List[str] = []
    if platform == "youtube":
        platform_tags = ["#Shorts"]
    elif platform == "tiktok":
        platform_tags = ["#fyp", "#틱톡"]
    tags_seq = platform_tags + _topic_hashtags(script.topic) + list(channel.hashtags)
    hashtags = _dedup_hashtags(tags_seq)[:max_hashtags]

    description = _build_description(script, channel, hashtags, platform)

    # 유튜브 검색 태그(설명과 별개, '#' 없는 키워드)
    seo_tags = _seo_tags(script, channel)

    return PublishMetadata(
        platform=platform,
        title=title,
        description=description,
        hashtags=hashtags,
        tags=seo_tags,
    )


def _build_description(
    script: MotivationScript,
    channel: ChannelProfile,
    hashtags: List[str],
    platform: str,
) -> str:
    lines: List[str] = []
    hook = _clean(script.hook())
    if hook:
        lines.append(hook)

    body = [b for b in script.body() if b.strip()]
    if body:
        lines.append("")
        for b in body[:3]:
            lines.append(f"• {_clean(b)}")

    cta = script.cta() or channel.cta
    if cta:
        lines.append("")
        lines.append(_clean(cta))

    sig = channel.signature()
    if sig:
        lines.append(f"— {sig}")

    if hashtags:
        lines.append("")
        lines.append(" ".join(hashtags))

    return "\n".join(lines).strip()


def _seo_tags(script: MotivationScript, channel: ChannelProfile) -> List[str]:
    """유튜브 검색 태그(키워드). 니치+주제+채널 키워드 조합, 중복 제거."""
    raw: List[str] = [channel.niche]
    raw.extend(channel.keywords)
    for tok in re.split(r"[\s/·,]+", script.topic):
        tok = tok.strip()
        if len(tok) >= 2:
            raw.append(tok)
    # 채널 해시태그도 키워드로(‘#’ 제거)
    for h in channel.hashtags:
        raw.append(h.lstrip("#"))

    seen: set = set()
    out: List[str] = []
    for t in raw:
        t = t.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:15]
