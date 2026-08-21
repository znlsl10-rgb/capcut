"""원시 스크레이퍼 JSON → 공통 ThreadPost 정규화.

Apify 의 Threads 액터들은 필드명이 제각각입니다(view_count / viewCount,
reply_count / directReplyCount, takenAt / created_at_timestamp …).
여기서 후보 키 목록으로 한 번에 흡수해서 아래 어떤 액터를 쓰든 동일하게 다룹니다.

  futurizerush/meta-threads-scraper   (조회수·공유수까지 제공, 기본값)
  igview-owner/threads-search-scraper
  burbn/threads-search-scraper
  automation-lab/threads-scraper  등
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

# --- 필드 후보 (앞에 있을수록 우선) --------------------------------------
_F_ID = ("post_id", "postId", "pk", "id", "post_code", "postCode")
_F_URL = ("post_url", "postUrl", "url", "permalink", "link")
_F_USER = ("username", "userName", "ownerUsername", "user_name", "author")
_F_NAME = ("display_name", "displayName", "full_name", "fullName", "name")
_F_FOLLOWERS = ("followers_count", "followersCount", "followers", "follower_count")
_F_TEXT = ("text_content", "captionText", "caption_text", "text", "caption", "content", "post_text")
_F_TS = ("created_at_timestamp", "takenAt", "taken_at", "timestamp", "created_timestamp")
_F_TS_STR = ("created_at", "takenAtISO", "taken_at_iso", "createdAt", "date", "published_at")
_F_VIEWS = ("view_count", "viewCount", "views", "play_count", "playCount", "impressions")
_F_LIKES = ("like_count", "likeCount", "likes", "likesCount", "favorite_count")
_F_REPLIES = ("reply_count", "replyCount", "directReplyCount", "direct_reply_count",
              "replies", "comment_count", "commentCount", "comments")
_F_REPOSTS = ("repost_count", "repostCount", "reposts", "retweet_count")
_F_QUOTES = ("quote_count", "quoteCount", "quotes")
_F_SHARES = ("share_count", "shareCount", "reshareCount", "reshare_count", "shares")
_F_IS_REPLY = ("is_reply", "isReply")
_F_IS_REPOST = ("is_repost", "isRepost")
_F_IS_AD = ("is_paid_partnership", "isPaidPartnership", "is_ad", "isAd")
_F_VERIFIED = ("is_verified", "isVerified", "verified")
_F_LANG = ("language", "lang", "detected_language")
_F_MEDIA_FLAG = ("has_media", "hasMedia")
_F_MEDIA_TYPE = ("media_type", "mediaType")
_F_MEDIA_URLS = ("media_urls", "mediaUrls", "allImages", "allVideos", "images", "videos")
_F_HASHTAGS = ("hashtags", "tags", "profile_tags")
_F_KEYWORD = ("search_keyword", "searchKeyword", "keyword", "query")

_HASHTAG_RE = re.compile(r"#([\w가-힣ぁ-んァ-ヶ一-龥]+)", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+")

# 스크립트(문자 체계) 판별용 코드 포인트 범위
_SCRIPT_RANGES = (
    ("ko", ((0xAC00, 0xD7A3), (0x1100, 0x11FF), (0x3130, 0x318F))),
    ("ja", ((0x3040, 0x309F), (0x30A0, 0x30FF))),
    ("zh", ((0x4E00, 0x9FFF), (0x3400, 0x4DBF))),
    ("ru", ((0x0400, 0x04FF),)),
    ("ar", ((0x0600, 0x06FF), (0x0750, 0x077F))),
    ("th", ((0x0E00, 0x0E7F),)),
    ("hi", ((0x0900, 0x097F),)),
    ("he", ((0x0590, 0x05FF),)),
    ("en", ((0x0041, 0x024F),)),
)


def _pick(raw: Dict[str, Any], keys: Sequence[str]) -> Any:
    for k in keys:
        if k in raw and raw[k] not in (None, "", [], {}):
            return raw[k]
    return None


def _as_int(value: Any) -> Optional[int]:
    """'1.2K', '3,456', 12.0 → int. 값이 없으면 None(=미제공)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(value)
    text = str(value).strip().replace(",", "").replace("+", "")
    if not text:
        return None
    mult = 1
    if text[-1].lower() in "kmb":
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[text[-1].lower()]
        text = text[:-1]
    try:
        return int(float(text) * mult)
    except ValueError:
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "y")
    return False


def _as_dt(raw: Dict[str, Any]) -> Optional[datetime]:
    ts = _pick(raw, _F_TS)
    if ts is not None:
        num = _as_int(ts)
        if num:
            if num > 10 ** 12:  # 밀리초
                num //= 1000
            try:
                return datetime.fromtimestamp(num, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                pass
    text = _pick(raw, _F_TS_STR)
    if isinstance(text, str):
        cleaned = text.strip().replace("Z", "+00:00").replace("/", "-")
        for candidate in (cleaned, cleaned.replace(" ", "T", 1)):
            try:
                dt = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def detect_script(text: str) -> str:
    """텍스트의 주 문자 체계 추정 ('ko' / 'en' / 'ja' / … / 'unknown')."""
    counts: Dict[str, int] = {}
    for ch in text:
        code = ord(ch)
        for name, ranges in _SCRIPT_RANGES:
            if any(lo <= code <= hi for lo, hi in ranges):
                counts[name] = counts.get(name, 0) + 1
                break
    if not counts:
        return "unknown"
    # 한글/일본어 가나는 소수만 섞여도 해당 언어권 글일 확률이 높다.
    total = sum(counts.values())
    for strong in ("ko", "ja", "th", "ar", "he", "hi", "ru"):
        if counts.get(strong, 0) / total >= 0.10:
            return strong
    return max(counts.items(), key=lambda kv: kv[1])[0]


def hangul_ratio(text: str) -> float:
    """전체 글자 중 한글 비율 (국내 글 제외용)."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    hangul = sum(1 for ch in letters if 0xAC00 <= ord(ch) <= 0xD7A3 or 0x3130 <= ord(ch) <= 0x318F)
    return hangul / len(letters)


@dataclass
class ThreadPost:
    """정규화된 스레드 게시물 1건."""

    post_id: str
    url: str
    username: str
    text: str
    created_at: Optional[datetime] = None
    display_name: str = ""
    followers: Optional[int] = None
    views: Optional[int] = None
    likes: int = 0
    replies: int = 0
    reposts: int = 0
    quotes: int = 0
    shares: int = 0
    is_reply: bool = False
    is_repost: bool = False
    is_ad: bool = False
    verified: bool = False
    language: str = ""
    has_media: bool = False
    media_type: str = ""
    hashtags: List[str] = field(default_factory=list)
    keyword: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    # --- 파생값 ---------------------------------------------------------
    @property
    def spread(self) -> int:
        """공유형 반응 = 리포스트 + 인용 + 공유."""
        return self.reposts + self.quotes + self.shares

    @property
    def engagement(self) -> int:
        return self.likes + self.replies + self.spread

    @property
    def age_hours(self) -> Optional[float]:
        if self.created_at is None:
            return None
        delta = datetime.now(timezone.utc) - self.created_at
        return max(delta.total_seconds() / 3600.0, 0.5)

    @property
    def text_length(self) -> int:
        return len(self.text)

    @property
    def first_line(self) -> str:
        for line in self.text.splitlines():
            if line.strip():
                return line.strip()
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "url": self.url,
            "username": self.username,
            "display_name": self.display_name,
            "followers": self.followers,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "views": self.views,
            "likes": self.likes,
            "replies": self.replies,
            "reposts": self.reposts,
            "quotes": self.quotes,
            "shares": self.shares,
            "spread": self.spread,
            "engagement": self.engagement,
            "language": self.language,
            "has_media": self.has_media,
            "media_type": self.media_type,
            "verified": self.verified,
            "is_reply": self.is_reply,
            "is_repost": self.is_repost,
            "hashtags": self.hashtags,
            "keyword": self.keyword,
            "text": self.text,
        }


def normalize_post(raw: Dict[str, Any]) -> Optional[ThreadPost]:
    """스크레이퍼 원시 레코드 1건 → ThreadPost. 게시물이 아니면 None."""
    if not isinstance(raw, dict):
        return None

    text = _pick(raw, _F_TEXT) or ""
    if not isinstance(text, str):
        text = str(text)
    url = _pick(raw, _F_URL) or ""
    post_id = _pick(raw, _F_ID)
    username = _pick(raw, _F_USER) or ""

    # 프로필/에러 레코드 등 게시물이 아닌 행은 버린다.
    record_type = str(raw.get("record_type") or raw.get("type") or "").lower()
    if record_type in ("profile", "user", "error"):
        return None
    if not text and not url:
        return None

    hashtags_raw = _pick(raw, _F_HASHTAGS) or []
    if isinstance(hashtags_raw, str):
        hashtags_raw = [hashtags_raw]
    hashtags = [str(h).lstrip("#").lower() for h in hashtags_raw if str(h).strip()]
    if not hashtags:
        hashtags = [m.lower() for m in _HASHTAG_RE.findall(text)]

    media_urls = _pick(raw, _F_MEDIA_URLS)
    has_media = _as_bool(_pick(raw, _F_MEDIA_FLAG)) or bool(media_urls) or bool(raw.get("media_url"))

    language = str(_pick(raw, _F_LANG) or "").lower()[:5]
    if not language:
        language = detect_script(text)

    return ThreadPost(
        post_id=str(post_id) if post_id else (url or text[:32]),
        url=str(url),
        username=str(username).lstrip("@"),
        text=text,
        created_at=_as_dt(raw),
        display_name=str(_pick(raw, _F_NAME) or ""),
        followers=_as_int(_pick(raw, _F_FOLLOWERS)),
        views=_as_int(_pick(raw, _F_VIEWS)),
        likes=_as_int(_pick(raw, _F_LIKES)) or 0,
        replies=_as_int(_pick(raw, _F_REPLIES)) or 0,
        reposts=_as_int(_pick(raw, _F_REPOSTS)) or 0,
        quotes=_as_int(_pick(raw, _F_QUOTES)) or 0,
        shares=_as_int(_pick(raw, _F_SHARES)) or 0,
        is_reply=_as_bool(_pick(raw, _F_IS_REPLY)),
        is_repost=_as_bool(_pick(raw, _F_IS_REPOST)),
        is_ad=_as_bool(_pick(raw, _F_IS_AD)),
        verified=_as_bool(_pick(raw, _F_VERIFIED)),
        language=language,
        has_media=has_media,
        media_type=str(_pick(raw, _F_MEDIA_TYPE) or ""),
        hashtags=hashtags,
        keyword=str(_pick(raw, _F_KEYWORD) or ""),
        raw=raw,
    )


def normalize_posts(items: Iterable[Dict[str, Any]]) -> List[ThreadPost]:
    """원시 레코드 목록 → ThreadPost 목록 (중복 URL/ID 제거)."""
    seen = set()
    posts: List[ThreadPost] = []
    for raw in items:
        post = normalize_post(raw)
        if post is None:
            continue
        key = post.url or post.post_id
        if key in seen:
            continue
        seen.add(key)
        posts.append(post)
    return posts


def strip_urls(text: str) -> str:
    return _URL_RE.sub(" ", text)
