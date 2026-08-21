"""상위 글 공통 패턴 분석 — '왜 터졌는가'를 숫자로.

  · 훅(첫 줄) 패턴별 성과      질문형 / 숫자형 / 리스트형 / 논쟁형 / 스토리형 …
  · 포맷별 성과                글 길이 구간, 사진·영상 유무
  · 시간대별 성과              KST 기준 발행 시각
  · 키워드/해시태그 lift        상위권에서 하위권보다 몇 배 자주 등장하는가
  · 계정별 성과
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from .models import strip_urls
from .score import ScoredPost

KST = timezone(timedelta(hours=9))

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")

_STOPWORDS = {
    "the", "and", "for", "you", "your", "that", "this", "with", "was", "are", "but", "not",
    "have", "has", "had", "they", "them", "there", "their", "what", "when", "who", "why",
    "how", "all", "can", "will", "just", "from", "about", "into", "out", "one", "get", "got",
    "its", "it's", "i'm", "don't", "doesn't", "didn't", "were", "been", "being", "would",
    "could", "should", "than", "then", "some", "more", "most", "much", "very", "even", "like",
    "make", "made", "here", "over", "after", "before", "because", "which", "these", "those",
    "our", "his", "her", "she", "him", "hers", "yours", "ours", "any", "own", "too", "now",
    "还", "www", "com", "https", "http",
}

# 훅 패턴: (이름, 설명, 판별 함수)
_HOOK_PATTERNS: Tuple[Tuple[str, str, "object"], ...] = (
    ("question", "질문형 — 첫 줄이 물음표로 끝남", lambda s: s.rstrip().endswith("?")),
    ("number", "숫자형 — 첫 줄에 숫자 포함", lambda s: bool(re.search(r"\d", s))),
    ("listicle", "리스트형 — 'N가지/N ways/top N'", lambda s: bool(re.search(r"\b(\d+)\s+(ways|things|tips|reasons|lessons|rules|steps|habits|mistakes)\b", s, re.I))),
    ("opinion", "논쟁형 — unpopular opinion / hot take / nobody talks", lambda s: bool(re.search(r"(unpopular opinion|hot take|controversial|nobody (talks|tells)|change my mind)", s, re.I))),
    ("howto", "방법형 — how to / here's how", lambda s: bool(re.search(r"(how to|here'?s how|step by step)", s, re.I))),
    ("story", "고백/스토리형 — I / my 로 시작", lambda s: bool(re.match(r"\s*(i|my|we)\b", s, re.I))),
    ("secret", "비밀/충격형 — secret / nobody / truth / stop", lambda s: bool(re.search(r"\b(secret|truth|stop doing|never|warning|shocking)\b", s, re.I))),
    ("cta_reply", "댓글유도형 — comment / drop / tell me", lambda s: bool(re.search(r"(comment|drop a|tell me|reply with|what do you think|thoughts\?)", s, re.I))),
    ("short_hook", "초단문 훅 — 첫 줄 40자 이하", lambda s: 0 < len(s.strip()) <= 40),
)

_LENGTH_BUCKETS = (
    ("초단문 (~80자)", 0, 80),
    ("단문 (81~200자)", 81, 200),
    ("중문 (201~400자)", 201, 400),
    ("장문 (401자~)", 401, 10 ** 9),
)


@dataclass
class GroupStat:
    """한 그룹(훅 유형/시간대/길이 구간 등)의 성과."""

    name: str
    count: int
    avg_score: float
    median_views: int
    avg_reply_rate: float
    avg_share_rate: float
    share: float          # 전체 대비 비중 0~1
    lift: float           # 전체 평균 점수 대비 배수

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "count": self.count,
            "avg_score": round(self.avg_score, 1),
            "median_views": self.median_views,
            "avg_reply_rate_pct": round(self.avg_reply_rate * 100, 3),
            "avg_share_rate_pct": round(self.avg_share_rate * 100, 3),
            "share_pct": round(self.share * 100, 1),
            "lift": round(self.lift, 2),
        }


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _group_stat(name: str, rows: Sequence[ScoredPost], total: int, base_avg: float) -> GroupStat:
    scores = [r.score for r in rows]
    avg = sum(scores) / len(scores) if scores else 0.0
    return GroupStat(
        name=name,
        count=len(rows),
        avg_score=avg,
        median_views=int(_median([r.effective_views for r in rows])),
        avg_reply_rate=sum(r.reply_rate for r in rows) / len(rows) if rows else 0.0,
        avg_share_rate=sum(r.share_rate for r in rows) / len(rows) if rows else 0.0,
        share=(len(rows) / total) if total else 0.0,
        lift=(avg / base_avg) if base_avg else 0.0,
    )


def hook_stats(rows: Sequence[ScoredPost], min_count: int = 3) -> List[GroupStat]:
    """훅(첫 줄) 패턴별 성과 — 한 글이 여러 패턴에 해당될 수 있음."""
    if not rows:
        return []
    base = sum(r.score for r in rows) / len(rows)
    out: List[GroupStat] = []
    for key, label, matcher in _HOOK_PATTERNS:
        hits = [r for r in rows if matcher(r.post.first_line)]
        if len(hits) < min_count:
            continue
        out.append(_group_stat(label, hits, len(rows), base))
    out.sort(key=lambda g: g.avg_score, reverse=True)
    return out


def length_stats(rows: Sequence[ScoredPost]) -> List[GroupStat]:
    if not rows:
        return []
    base = sum(r.score for r in rows) / len(rows)
    out = []
    for label, lo, hi in _LENGTH_BUCKETS:
        hits = [r for r in rows if lo <= r.post.text_length <= hi]
        if hits:
            out.append(_group_stat(label, hits, len(rows), base))
    return out


def media_stats(rows: Sequence[ScoredPost]) -> List[GroupStat]:
    if not rows:
        return []
    base = sum(r.score for r in rows) / len(rows)
    out = []
    for label, pred in (("사진/영상 있음", True), ("텍스트만", False)):
        hits = [r for r in rows if r.post.has_media is pred]
        if hits:
            out.append(_group_stat(label, hits, len(rows), base))
    return out


def hour_stats(rows: Sequence[ScoredPost], min_count: int = 2) -> List[GroupStat]:
    """KST 기준 발행 시간대별 성과."""
    dated = [r for r in rows if r.post.created_at]
    if not dated:
        return []
    base = sum(r.score for r in dated) / len(dated)
    buckets: Dict[int, List[ScoredPost]] = defaultdict(list)
    for row in dated:
        buckets[row.post.created_at.astimezone(KST).hour].append(row)
    out = [
        _group_stat(f"{hour:02d}시(KST)", group, len(dated), base)
        for hour, group in sorted(buckets.items())
        if len(group) >= min_count
    ]
    return out


def _tokens(text: str) -> List[str]:
    body = strip_urls(text).lower()
    return [w for w in _WORD_RE.findall(body) if w not in _STOPWORDS]


@dataclass
class TermLift:
    term: str
    top_count: int
    rest_count: int
    lift: float
    avg_score: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "term": self.term,
            "top_count": self.top_count,
            "rest_count": self.rest_count,
            "lift": round(self.lift, 2),
            "avg_score": round(self.avg_score, 1),
        }


def term_lift(
    rows: Sequence[ScoredPost],
    *,
    top_ratio: float = 0.25,
    min_top_count: int = 2,
    limit: int = 25,
    hashtags_only: bool = False,
) -> List[TermLift]:
    """상위권에서 유독 자주 나오는 단어/해시태그 (lift = 상위 등장률 / 하위 등장률)."""
    if len(rows) < 4:
        return []
    ordered = sorted(rows, key=lambda r: r.score, reverse=True)
    cut = max(int(len(ordered) * top_ratio), 1)
    top, rest = ordered[:cut], ordered[cut:]
    if not rest:
        return []

    def counter(group: Sequence[ScoredPost]) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for row in group:
            terms = set(row.post.hashtags) if hashtags_only else set(_tokens(row.post.text))
            for term in terms:
                counts[term] += 1
        return counts

    top_counts, rest_counts = counter(top), counter(rest)
    scores_by_term: Dict[str, List[float]] = defaultdict(list)
    for row in ordered:
        terms = set(row.post.hashtags) if hashtags_only else set(_tokens(row.post.text))
        for term in terms:
            scores_by_term[term].append(row.score)

    out: List[TermLift] = []
    for term, tc in top_counts.items():
        if tc < min_top_count:
            continue
        top_rate = tc / len(top)
        rest_rate = (rest_counts.get(term, 0) + 0.5) / len(rest)  # 라플라스 보정
        scores = scores_by_term[term]
        out.append(
            TermLift(
                term=term,
                top_count=tc,
                rest_count=rest_counts.get(term, 0),
                lift=top_rate / rest_rate,
                avg_score=sum(scores) / len(scores),
            )
        )
    out.sort(key=lambda t: (t.lift, t.top_count), reverse=True)
    return out[:limit]


def author_stats(rows: Sequence[ScoredPost], min_posts: int = 2, limit: int = 15) -> List[Dict[str, object]]:
    groups: Dict[str, List[ScoredPost]] = defaultdict(list)
    for row in rows:
        if row.post.username:
            groups[row.post.username].append(row)
    out = []
    for username, group in groups.items():
        if len(group) < min_posts:
            continue
        followers = next((g.post.followers for g in group if g.post.followers), None)
        out.append(
            {
                "username": username,
                "posts": len(group),
                "avg_score": round(sum(g.score for g in group) / len(group), 1),
                "median_views": int(_median([g.effective_views for g in group])),
                "followers": followers,
                "best_url": max(group, key=lambda g: g.score).post.url,
            }
        )
    out.sort(key=lambda d: d["avg_score"], reverse=True)
    return out[:limit]


def summary(rows: Sequence[ScoredPost]) -> Dict[str, object]:
    if not rows:
        return {"count": 0}
    views = [r.effective_views for r in rows]
    estimated = sum(1 for r in rows if r.views_estimated)
    return {
        "count": len(rows),
        "median_views": int(_median(views)),
        "max_views": int(max(views)),
        "median_likes": int(_median([r.post.likes for r in rows])),
        "median_replies": int(_median([r.post.replies for r in rows])),
        "median_spread": int(_median([r.post.spread for r in rows])),
        "avg_reply_rate_pct": round(sum(r.reply_rate for r in rows) / len(rows) * 100, 3),
        "avg_share_rate_pct": round(sum(r.share_rate for r in rows) / len(rows) * 100, 3),
        "views_estimated_ratio_pct": round(estimated / len(rows) * 100, 1),
        "languages": _language_mix(rows),
    }


def _language_mix(rows: Sequence[ScoredPost], limit: int = 6) -> List[Dict[str, object]]:
    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.post.language or "unknown"] += 1
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"language": k, "count": v} for k, v in ordered]


def analyze(rows: Sequence[ScoredPost]) -> Dict[str, object]:
    """전체 분석 결과 묶음 (리포트/웹 UI 공용)."""
    return {
        "summary": summary(rows),
        "hooks": [g.to_dict() for g in hook_stats(rows)],
        "lengths": [g.to_dict() for g in length_stats(rows)],
        "media": [g.to_dict() for g in media_stats(rows)],
        "hours": [g.to_dict() for g in hour_stats(rows)],
        "keywords": [t.to_dict() for t in term_lift(rows)],
        "hashtags": [t.to_dict() for t in term_lift(rows, hashtags_only=True, limit=15)],
        "authors": author_stats(rows),
    }
