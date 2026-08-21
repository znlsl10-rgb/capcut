"""한국어 스레드 글 초안 생성 — 터진 해외 글 → 번역/리라이트 + 쿠팡 파트너스 링크.

만들어지는 형태(스레드에 그대로 붙여넣기 가능):

    [훅 1줄]                      ← 원문 훅 유형(질문/숫자/후기…)을 한국어로 재현
    [본문 3~5줄]                  ← 원문 번역을 스레드 호흡(짧은 줄)으로 재배치
    [제품 한 줄 + 가격/로켓 여부]
    👉 [쿠팡 파트너스 링크]
    [댓글 유도 질문]              ← 댓글 수가 노출을 끌어올리므로 항상 포함
    #해시태그

    ※ 쿠팡 파트너스 활동의 일환으로 수수료를 제공받습니다.   ← 법적 필수 고지(자동)

번역은 deep-translator 가 있으면 자동, 없으면 원문을 남기고 경고를 답니다.
그대로 복붙하지 말고 자기 말투로 한 번 고쳐 쓰는 걸 권장합니다(중복 콘텐츠 방지).
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .coupang import CoupangMatch, CoupangProduct
from .product import ProductLead
from .score import ScoredPost

# 쿠팡 파트너스 필수 고지 문구 (2024년 이후 표준 문구)
DISCLOSURE = "이 게시물은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

# 원문 훅 유형 → 한국어 훅 템플릿
_HOOK_TEMPLATES: Dict[str, str] = {
    "question": "{topic}, 아직도 그냥 참고 쓰세요?",
    "number": "{topic} 사기 전에 이거 하나만 보세요.",
    "listicle": "{topic} 고를 때 이 3가지만 보면 됩니다.",
    "opinion": "솔직히 말할게요. {topic}은 대부분 잘못 고릅니다.",
    "howto": "{topic}, 이렇게 쓰니까 완전 달라졌어요.",
    "story": "{topic} 하나 바꿨더니 생활이 바뀌었습니다.",
    "secret": "{topic} 살 때 아무도 안 알려주는 것.",
    "default": "{topic} 하나로 이만큼 편해질 줄 몰랐습니다.",
}

_CTAS = (
    "여러분은 어떤 거 쓰세요? 댓글로 알려주세요 👇",
    "혹시 더 좋은 제품 아시는 분? 댓글 부탁드려요 👇",
    "궁금한 거 댓글 주시면 아는 만큼 답변드릴게요 👇",
    "이거 살까 말까 고민되면 댓글 남겨주세요 👇",
)

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class KoreanDraft:
    """스레드 업로드용 한국어 초안."""

    source_url: str
    hook: str
    body_lines: List[str]
    product_line: str
    link_line: str
    cta: str
    hashtags: List[str]
    disclosure: str = DISCLOSURE
    translated: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        parts = [self.hook, ""]
        parts.extend(self.body_lines)
        if self.product_line:
            parts += ["", self.product_line]
        if self.link_line:
            parts.append(self.link_line)
        parts += ["", self.cta]
        if self.hashtags:
            parts.append(" ".join(f"#{h}" for h in self.hashtags))
        parts += ["", self.disclosure]
        return "\n".join(parts).strip()

    @property
    def char_count(self) -> int:
        return len(self.text)

    def to_dict(self) -> Dict[str, object]:
        return {
            "source_url": self.source_url,
            "hook": self.hook,
            "body": self.body_lines,
            "product_line": self.product_line,
            "link_line": self.link_line,
            "cta": self.cta,
            "hashtags": self.hashtags,
            "disclosure": self.disclosure,
            "translated": self.translated,
            "warnings": self.warnings,
            "text": self.text,
            "char_count": self.char_count,
        }


# --- 번역 ---------------------------------------------------------------
def translate_text(text: str, *, source: str = "auto", target: str = "ko") -> Optional[str]:
    """deep-translator 로 번역. 없거나 실패하면 None (호출부에서 원문 유지)."""
    if not text.strip():
        return ""
    try:
        from deep_translator import GoogleTranslator  # noqa: WPS433
    except ImportError:
        return None
    try:
        translator = GoogleTranslator(source=source, target=target)
        # 5000자 제한 → 넉넉히 잘라서 보냄
        chunks = textwrap.wrap(text, 4500, replace_whitespace=False, drop_whitespace=False) or [text]
        return "".join(translator.translate(chunk) or "" for chunk in chunks)
    except Exception:  # noqa: BLE001 — 네트워크/쿼터 문제 시 원문 유지
        return None


def _hook_kind(first_line: str) -> str:
    line = first_line.strip()
    if re.search(r"(unpopular opinion|hot take|controversial)", line, re.I):
        return "opinion"
    if re.search(r"\b(\d+)\s+(ways|things|tips|reasons|rules|steps|mistakes)\b", line, re.I):
        return "listicle"
    if re.search(r"(how to|here'?s how)", line, re.I):
        return "howto"
    if re.search(r"\b(secret|truth|nobody|never|stop)\b", line, re.I):
        return "secret"
    if line.endswith("?"):
        return "question"
    if re.search(r"\d", line):
        return "number"
    if re.match(r"\s*(i|my|we)\b", line, re.I):
        return "story"
    return "default"


def _topic(lead: ProductLead, product: Optional[CoupangProduct]) -> str:
    if lead.search_terms:
        return lead.search_terms[0]
    if product and product.name:
        return product.name.split()[0]
    return "이 제품"


def _body_from(text: str, *, limit_lines: int = 5, line_width: int = 60) -> List[str]:
    """번역문을 스레드 호흡(짧은 줄)으로 재배치."""
    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]
    lines: List[str] = []
    for sentence in sentences:
        if len(sentence) <= line_width:
            lines.append(sentence)
        else:
            lines.extend(textwrap.wrap(sentence, line_width))
        if len(lines) >= limit_lines:
            break
    return lines[:limit_lines]


def _hashtags(lead: ProductLead, product: Optional[CoupangProduct]) -> List[str]:
    tags: List[str] = []
    for term in lead.search_terms[:2]:
        tag = re.sub(r"\s+", "", term)
        if tag and tag not in tags:
            tags.append(tag)
    if product and product.is_rocket:
        tags.append("로켓배송")
    for extra in ("쿠팡추천", "생활템"):
        if extra not in tags:
            tags.append(extra)
    return tags[:5]


def build_draft(
    row: ScoredPost,
    lead: ProductLead,
    match: Optional[CoupangMatch] = None,
    *,
    translate: bool = True,
    cta_index: int = 0,
) -> KoreanDraft:
    """터진 해외 글 1건 → 한국어 스레드 초안 1건."""
    post = row.post
    warnings: List[str] = []

    translated_text = translate_text(post.text) if translate else None
    if translate and translated_text is None:
        warnings.append("자동 번역 불가(deep-translator 미설치 또는 네트워크 오류) — 원문을 그대로 넣었습니다.")
    body_source = translated_text or post.text
    body_lines = _body_from(body_source)

    product = match.product if match and match.found else None
    topic = _topic(lead, product)
    hook = _HOOK_TEMPLATES[_hook_kind(post.first_line)].format(topic=topic)

    if product:
        bits = [product.name.strip()[:60]]
        if product.price:
            bits.append(f"{product.price:,}원")
        if product.is_rocket:
            bits.append("로켓배송")
        product_line = "🛒 " + " · ".join(bits)
        link_line = f"👉 {product.url}"
        if not product.affiliate:
            warnings.append("제휴 링크가 아닙니다 — 쿠팡 파트너스에서 딥링크로 변환한 뒤 올리세요.")
    else:
        product_line = ""
        link_line = "👉 (쿠팡 파트너스 링크 넣기)"
        warnings.append("쿠팡에서 매칭 상품을 찾지 못했습니다 — 직접 검색해 링크를 넣으세요.")

    if post.views and post.views < 1000:
        warnings.append("원문 노출이 낮은 편 — 다른 소재를 먼저 쓰는 게 안전합니다.")

    return KoreanDraft(
        source_url=post.url,
        hook=hook,
        body_lines=body_lines,
        product_line=product_line,
        link_line=link_line,
        cta=_CTAS[cta_index % len(_CTAS)],
        hashtags=_hashtags(lead, product),
        translated=bool(translated_text),
        warnings=warnings,
    )


def build_drafts(
    rows: Sequence[ScoredPost],
    leads: Dict[str, ProductLead],
    matches: Dict[str, CoupangMatch],
    *,
    translate: bool = True,
    limit: int = 10,
) -> List[KoreanDraft]:
    drafts: List[KoreanDraft] = []
    for idx, row in enumerate(rows[:limit]):
        lead = leads.get(row.post.url)
        if lead is None:
            continue
        drafts.append(
            build_draft(row, lead, matches.get(row.post.url), translate=translate, cta_index=idx)
        )
    return drafts
