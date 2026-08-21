"""게시물 텍스트에서 '팔 수 있는 제품' 뽑아내기.

목표: 해외 스레드에서 터진 글 중 **쿠팡에 파는 물건과 엮을 수 있는 글**만 골라
      쿠팡 검색용 한국어 키워드까지 만들어 준다.

  1) 커머스 의도 점수   구매/추천/링크/가격 신호가 몇 개나 있는가
  2) 제품 후보 추출     카테고리 사전(영→한) + 브랜드형 고유명사 + 해시태그
  3) 검색어 생성        쿠팡에서 실제로 검색할 한국어 키워드
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .models import ThreadPost, strip_urls

# --- 커머스 의도 신호 ----------------------------------------------------
_INTENT_PATTERNS = (
    (r"\b(bought|buying|purchased|ordered|got mine|repurchase)\b", 2, "구매 경험"),
    (r"\b(amazon|link in bio|link below|shop|store|checkout|affiliate)\b", 2, "구매 링크"),
    (r"[$€£¥]\s?\d|\b\d+\s?(usd|dollars|bucks)\b", 2, "가격 언급"),
    (r"\b(worth it|game changer|life changing|must have|must-have|obsessed with)\b", 2, "강력 추천"),
    (r"\b(review|unboxing|tested|tried|using it for|after \d+ (days|weeks|months))\b", 1, "사용 후기"),
    (r"\b(recommend|recommendation|favorite|favourite|best \w+ (for|under))\b", 1, "추천"),
    (r"\b(deal|sale|discount|coupon|off\b|cheap|budget|under \$?\d+)\b", 1, "가격/할인"),
    (r"\b(gift|gifts|gift guide|christmas|birthday present)\b", 1, "선물"),
    (r"\b(hack|hacks|essentials|setup|routine|haul|favorites)\b", 1, "아이템 나열"),
)

# --- 제품 카테고리 사전 (영어 표현 → 쿠팡 검색용 한국어) -----------------
# 스레드에서 자주 터지고 쿠팡에서 잘 팔리는 카테고리 위주.
PRODUCT_LEXICON: Dict[str, str] = {
    # 주방/생활
    "air fryer": "에어프라이어", "airfryer": "에어프라이어",
    "rice cooker": "전기밥솥", "blender": "믹서기", "coffee maker": "커피메이커",
    "espresso machine": "에스프레소 머신", "kettle": "전기포트", "water bottle": "텀블러",
    "tumbler": "텀블러", "food container": "밀폐용기", "knife set": "칼세트",
    "cutting board": "도마", "frying pan": "프라이팬", "cast iron": "무쇠팬",
    "vacuum": "무선청소기", "robot vacuum": "로봇청소기", "air purifier": "공기청정기",
    "humidifier": "가습기", "dehumidifier": "제습기", "steam mop": "스팀청소기",
    "mattress topper": "매트리스 토퍼", "pillow": "베개", "blackout curtain": "암막커튼",
    "storage box": "수납함", "organizer": "정리함", "label maker": "라벨메이커",
    # 전자/IT
    "earbuds": "무선이어폰", "headphones": "헤드폰", "noise cancelling": "노이즈캔슬링 이어폰",
    "power bank": "보조배터리", "charger": "충전기", "usb hub": "USB 허브",
    "monitor": "모니터", "monitor arm": "모니터암", "mechanical keyboard": "기계식 키보드",
    "keyboard": "키보드", "mouse": "마우스", "webcam": "웹캠", "microphone": "마이크",
    "ssd": "외장SSD", "laptop stand": "노트북 거치대", "tablet": "태블릿",
    "smart watch": "스마트워치", "smartwatch": "스마트워치", "e-reader": "이북리더기",
    "projector": "빔프로젝터", "ring light": "링라이트", "tripod": "삼각대",
    "gimbal": "짐벌", "action camera": "액션캠", "drone": "드론",
    # 건강/운동
    "resistance band": "밴드 운동밴드", "dumbbell": "덤벨", "kettlebell": "케틀벨",
    "yoga mat": "요가매트", "foam roller": "폼롤러", "massage gun": "마사지건",
    "treadmill": "런닝머신", "exercise bike": "실내자전거", "jump rope": "줄넘기",
    "protein powder": "단백질 보충제", "creatine": "크레아틴", "multivitamin": "종합비타민",
    "magnesium": "마그네슘", "omega 3": "오메가3", "probiotic": "유산균",
    "collagen": "콜라겐", "electrolyte": "전해질 음료",
    # 뷰티/퍼스널케어
    "sunscreen": "선크림", "retinol": "레티놀", "vitamin c serum": "비타민C 세럼",
    "hyaluronic acid": "히알루론산 세럼", "moisturizer": "수분크림", "cleanser": "클렌저",
    "sheet mask": "마스크팩", "lip balm": "립밤", "hair dryer": "헤어드라이어",
    "straightener": "고데기", "electric toothbrush": "전동칫솔", "water flosser": "구강세정기",
    "razor": "면도기", "trimmer": "바리깡", "perfume": "향수",
    # 수면/집중/작업
    "standing desk": "스탠딩 데스크", "office chair": "사무용 의자", "ergonomic chair": "인체공학 의자",
    "desk lamp": "스탠드 조명", "white noise machine": "백색소음기", "sleep mask": "수면안대",
    "ear plugs": "귀마개", "weighted blanket": "중량 담요", "planner": "다이어리",
    "notebook": "노트", "fountain pen": "만년필", "highlighter": "형광펜",
    # 반려/육아/자동차
    "dog bed": "강아지 방석", "cat tree": "캣타워", "pet hair remover": "반려동물 털제거기",
    "stroller": "유모차", "car seat": "카시트", "baby monitor": "베이비모니터",
    "dash cam": "블랙박스", "car vacuum": "차량용 청소기", "phone mount": "차량용 거치대",
    "tire inflator": "타이어 공기주입기",
}

# 텍스트에서 브랜드/제품명처럼 보이는 고유명사 (대문자 시작 1~3단어)
_PROPER_RE = re.compile(r"\b([A-Z][a-zA-Z0-9\-]{2,}(?:\s+[A-Z0-9][a-zA-Z0-9\-]{1,}){0,2})\b")
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?\n]\s+)([A-Z])")
_GENERIC_PROPER = {
    "I", "The", "This", "That", "My", "Your", "You", "We", "It", "But", "And", "So", "If",
    "When", "What", "Why", "How", "Here", "There", "Just", "Now", "Today", "Every", "One",
    "Threads", "Instagram", "Twitter", "TikTok", "YouTube", "Facebook", "Reddit", "Google",
    "AI", "US", "USA", "UK", "OK", "PS", "DM", "TLDR",
}


@dataclass
class ProductLead:
    """게시물 1건에서 뽑아낸 '팔 거리'."""

    post_url: str
    intent_score: int                       # 커머스 의도 점수(신호 가중합)
    intent_signals: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)   # 사전에 걸린 영어 표현
    search_terms: List[str] = field(default_factory=list) # 쿠팡 검색용 한국어 키워드
    brands: List[str] = field(default_factory=list)       # 브랜드/제품명 후보

    @property
    def sellable(self) -> bool:
        """쿠팡 매칭을 시도할 가치가 있는가."""
        return bool(self.search_terms) and self.intent_score >= 1

    def to_dict(self) -> Dict[str, object]:
        return {
            "post_url": self.post_url,
            "intent_score": self.intent_score,
            "intent_signals": self.intent_signals,
            "categories": self.categories,
            "search_terms": self.search_terms,
            "brands": self.brands,
            "sellable": self.sellable,
        }


def commerce_intent(text: str) -> tuple[int, List[str]]:
    """구매/추천/가격 신호를 세어 커머스 의도 점수를 낸다."""
    score = 0
    signals: List[str] = []
    for pattern, weight, label in _INTENT_PATTERNS:
        if re.search(pattern, text, re.I):
            score += weight
            signals.append(label)
    return score, signals


def find_categories(text: str) -> List[str]:
    """사전에 등록된 제품 카테고리 표현 찾기 (긴 표현 우선)."""
    lowered = strip_urls(text).lower()
    found: List[str] = []
    for phrase in sorted(PRODUCT_LEXICON, key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", lowered):
            # 이미 더 긴 표현에 포함됐으면 건너뛴다 ("air fryer" ⊃ "fryer")
            if any(phrase in seen for seen in found):
                continue
            found.append(phrase)
    return found


def find_brands(text: str, limit: int = 5) -> List[str]:
    """브랜드/제품명 후보 (문장 첫 단어·흔한 단어 제외)."""
    body = strip_urls(text)
    sentence_starts = {m.start(1) for m in _SENTENCE_START_RE.finditer(body)}
    out: List[str] = []
    for match in _PROPER_RE.finditer(body):
        token = match.group(1).strip()
        head = token.split()[0]
        if head in _GENERIC_PROPER or len(token) < 3:
            continue
        if match.start(1) in sentence_starts and " " not in token:
            continue  # 문장 첫 단어 한 개짜리는 그냥 대문자일 뿐
        if token not in out:
            out.append(token)
        if len(out) >= limit:
            break
    return out


def extract_lead(post: ThreadPost) -> ProductLead:
    """게시물 → ProductLead (제품 추출 + 쿠팡 검색어 생성)."""
    text = post.text
    score, signals = commerce_intent(text)
    categories = find_categories(text)
    brands = find_brands(text)

    search_terms: List[str] = []
    for phrase in categories:
        korean = PRODUCT_LEXICON[phrase]
        if korean not in search_terms:
            search_terms.append(korean)
    # 브랜드 + 카테고리 조합은 더 정확한 검색어가 된다 ("Anker 보조배터리").
    if brands and categories:
        combo = f"{brands[0]} {PRODUCT_LEXICON[categories[0]]}"
        search_terms.insert(0, combo)
    # 해시태그도 카테고리 사전에 걸리면 검색어로 사용.
    for tag in post.hashtags:
        korean = PRODUCT_LEXICON.get(tag.replace("_", " ").lower())
        if korean and korean not in search_terms:
            search_terms.append(korean)

    return ProductLead(
        post_url=post.url,
        intent_score=score,
        intent_signals=signals,
        categories=categories,
        search_terms=search_terms[:4],
        brands=brands,
    )


def extract_leads(posts: Sequence[ThreadPost]) -> List[ProductLead]:
    return [extract_lead(p) for p in posts]


def lexicon_terms() -> List[str]:
    """사전에 등록된 한국어 검색어 전체 (쿠팡 카테고리 탐색용)."""
    return sorted(set(PRODUCT_LEXICON.values()))
