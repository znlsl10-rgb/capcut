"""주제별 키워드 프리셋 — 뭘 검색해야 할지 고민하지 않도록.

    python -m threadscout scan --preset beauty

프리셋은 '쿠팡에서 잘 팔리는 카테고리 × 해외 스레드에서 반응 좋은 주제' 교집합으로 골랐다.
직접 키워드를 섞고 싶으면 -k 로 추가하면 된다 (프리셋 + 추가 키워드가 합쳐진다).
"""

from __future__ import annotations

from typing import Dict, List, Sequence

PRESETS: Dict[str, List[str]] = {
    # 반복 구매가 많아 수수료 누적에 유리 (요율도 뷰티 7% / 헬스 5% 수준)
    "beauty": [
        "skincare routine", "skin barrier", "sunscreen", "retinol",
        "hair loss", "supplements", "gut health", "sleep routine",
    ],
    # 매칭률이 가장 높은 영역
    "kitchen": [
        "amazon finds", "air fryer", "kitchen gadget", "meal prep",
        "home hacks", "cleaning hack",
    ],
    # 단가가 높고 리뷰형 콘텐츠가 잘 먹힘
    "desk": [
        "desk setup", "home office", "tech accessories", "productivity setup",
        "work from home", "monitor setup",
    ],
    # 댓글 반응(충성도)이 강한 영역
    "pet": [
        "pet hacks", "dog essentials", "cat products", "puppy tips",
    ],
    "baby": [
        "baby essentials", "newborn must haves", "toddler hacks", "mom hacks",
    ],
    "fitness": [
        "gym essentials", "home workout", "creatine", "protein powder",
        "running gear", "recovery tools",
    ],
}


def preset_keywords(names: Sequence[str]) -> List[str]:
    """프리셋 이름들 → 키워드 목록(중복 제거, 순서 유지)."""
    out: List[str] = []
    for name in names:
        for keyword in PRESETS.get(name.lower(), []):
            if keyword not in out:
                out.append(keyword)
    return out


def preset_names() -> List[str]:
    return sorted(PRESETS)
