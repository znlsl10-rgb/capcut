"""채널 프로필 — 브랜딩/톤/CTA/해시태그.

동기부여 쇼츠의 "정체성"을 담습니다. 노션 브랜딩 문서가 확정되면 이 프로필
YAML 하나만 채우면 모든 대본·자막·게시 메타데이터에 일관되게 반영됩니다.

의존성 없이(YAML 로더만 지연 임포트) 동작하므로 단독 테스트 가능합니다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# 톤 → 캡컷 스타일 프리셋 매핑(transitions.PRESETS).
# 동기부여는 가독성 높은 굵은 자막이 핵심이라 기본은 'motivation' 프리셋.
_TONE_STYLE = {
    "강렬": "motivation",
    "시네마틱": "cinematic",
    "담백": "motivation",
    "따뜻": "cinematic",
}

_DEFAULT_HASHTAGS = ["#동기부여", "#자기계발", "#성공마인드", "#shorts", "#명언"]


@dataclass
class ChannelProfile:
    """유튜브(+틱톡) 동기부여 채널의 브랜딩 프로필.

    Attributes:
        name: 채널 이름(브랜드).
        handle: 핸들(@없이 또는 있이). 설명란 서명에 사용.
        niche: 세부 니치(예: "성공 동기부여", "새벽 루틴", "부의 마인드셋").
        language: 콘텐츠 언어 코드(ko/en/…). 자막/나레이션/메타 기본 언어.
        tone: 톤("강렬"/"시네마틱"/"담백"/"따뜻"). 캡컷 스타일 자동 선택에 사용.
        persona: 화자 페르소나(1인칭 관점 한 줄). 대본 톤을 잡는 힌트.
        cta: 고정 콜투액션(구독 유도 문구). 아웃트로 자막/설명란에 삽입.
        hook_signature: 채널 고정 오프닝 훅 접두(선택). 예 "3초만 볼게요".
        hashtags: 기본 해시태그(모든 영상 공통). 주제별 해시태그와 합쳐짐.
        keywords: 검색 태그 시드(주제 키워드와 합쳐짐).
        banned_words: 대본/자막에서 피할 단어(브랜드 세이프티).
        style: 캡컷 프리셋 이름 직접 지정(없으면 tone 으로 자동).
        watermark: 화면 고정 워터마크 텍스트(핸들 등, 선택).
    """

    name: str
    handle: str = ""
    niche: str = "성공 동기부여"
    language: str = "ko"
    tone: str = "강렬"
    persona: str = ""
    cta: str = "구독하고 매일 함께 성장해요"
    hook_signature: str = ""
    hashtags: List[str] = field(default_factory=lambda: list(_DEFAULT_HASHTAGS))
    keywords: List[str] = field(default_factory=list)
    banned_words: List[str] = field(default_factory=list)
    style: Optional[str] = None
    watermark: str = ""

    def resolved_style(self) -> str:
        """캡컷 프리셋 이름. style 직접 지정이 우선, 없으면 tone 으로 매핑."""
        if self.style:
            return self.style
        return _TONE_STYLE.get(self.tone, "motivation")

    def signature(self) -> str:
        """설명란 서명(핸들/채널명)."""
        h = self.handle.strip()
        if h and not h.startswith("@"):
            h = "@" + h
        return h or self.name

    def normalized_hashtags(self) -> List[str]:
        """중복 제거 + '#' 접두 보정된 해시태그 목록(순서 유지)."""
        return _dedup_hashtags(self.hashtags)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _dedup_hashtags(tags: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for t in tags:
        t = t.strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


_KNOWN = set(ChannelProfile.__dataclass_fields__.keys())


def from_dict(data: Dict[str, Any]) -> ChannelProfile:
    """dict → ChannelProfile. 알 수 없는 키는 무시(관대하게)."""
    if "name" not in data or not str(data.get("name", "")).strip():
        raise ValueError("채널 프로필에 'name'(채널 이름)이 필요합니다.")
    known = {k: v for k, v in data.items() if k in _KNOWN}
    return ChannelProfile(**known)


def load_channel(path: str) -> ChannelProfile:
    """YAML 채널 프로필을 읽어 ChannelProfile 로 변환."""
    import yaml  # 지연 임포트

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("채널 프로필 YAML 의 최상위는 매핑(dict)이어야 합니다.")
    return from_dict(data)


def default_channel(name: str = "성공 동기부여") -> ChannelProfile:
    """브랜딩 확정 전 임시로 쓰는 기본 프로필."""
    return ChannelProfile(name=name)
