"""쿠팡 매칭 — '이 글에서 밀 수 있는 물건이 쿠팡에 있나?' + 파트너스 링크.

두 가지 경로를 지원합니다.

A) 쿠팡 파트너스 Open API  (권장, 키 필요 / 제휴 링크까지 한 번에)
     export COUPANG_ACCESS_KEY=...  COUPANG_SECRET_KEY=...
     - 상품 검색: 검색어로 상품 + 이미 제휴 추적이 붙은 productUrl 반환
     - 딥링크   : 임의의 쿠팡 URL → 내 파트너스 링크로 변환
     - 골드박스 : 매일 할인 상품(콘텐츠 소재로 좋음)

B) Apify 쿠팡 검색 액터  (키 없이 '판매 여부'만 확인할 때)
     zen-studio/coupang-search-scraper — 가격·평점·리뷰수까지 확인 가능.
     제휴 링크는 못 만들므로, 최종 링크는 파트너스에서 별도 생성해야 합니다.

주의: 쿠팡 파트너스 링크를 쓴 글에는 **대가성 문구 고지가 필수**입니다(draft.py 가 자동 삽입).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

DOMAIN = "https://api-gateway.coupang.com"
SEARCH_PATH = "/v2/providers/affiliate_open_api/apis/openapi/products/search"
DEEPLINK_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
GOLDBOX_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/goldbox"
BESTCATEGORY_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/bestcategories/{cid}"

COUPANG_SEARCH_ACTOR = "zen-studio/coupang-search-scraper"

# 카테고리별 대략 수수료율(파트너스 정책은 변동됨 → 수익 '추정'에만 사용).
DEFAULT_COMMISSION_RATE = 0.03
COMMISSION_RATES: Dict[str, float] = {
    "패션의류": 0.10, "패션잡화": 0.10, "뷰티": 0.07, "출산/유아동": 0.05,
    "식품": 0.04, "주방용품": 0.04, "생활용품": 0.04, "홈인테리어": 0.04,
    "가전디지털": 0.03, "컴퓨터/노트북": 0.03, "스포츠/레저": 0.05,
    "자동차용품": 0.05, "도서/음반/DVD": 0.03, "완구/취미": 0.05,
    "반려동물용품": 0.05, "헬스/건강식품": 0.05,
}

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


class CoupangError(RuntimeError):
    pass


@dataclass
class CoupangProduct:
    """쿠팡 상품 1건 (파트너스 API / Apify 공통 형태)."""

    name: str
    url: str
    price: Optional[int] = None
    image: str = ""
    product_id: str = ""
    category: str = ""
    is_rocket: bool = False
    is_free_shipping: bool = False
    rating: Optional[float] = None
    review_count: Optional[int] = None
    affiliate: bool = False        # url 이 이미 파트너스 링크인가
    match_score: float = 0.0       # 검색어와의 일치도 0~1
    source: str = "partners"

    @property
    def commission_rate(self) -> float:
        for key, rate in COMMISSION_RATES.items():
            if key and key in (self.category or ""):
                return rate
        return DEFAULT_COMMISSION_RATE

    @property
    def commission_per_sale(self) -> Optional[int]:
        if not self.price:
            return None
        return int(self.price * self.commission_rate)

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "url": self.url,
            "price": self.price,
            "image": self.image,
            "product_id": self.product_id,
            "category": self.category,
            "is_rocket": self.is_rocket,
            "is_free_shipping": self.is_free_shipping,
            "rating": self.rating,
            "review_count": self.review_count,
            "affiliate": self.affiliate,
            "match_score": round(self.match_score, 2),
            "commission_rate_pct": round(self.commission_rate * 100, 1),
            "commission_per_sale": self.commission_per_sale,
            "source": self.source,
        }


# --- 파트너스 Open API ---------------------------------------------------
def _hmac_authorization(method: str, path_with_query: str, access_key: str, secret_key: str) -> str:
    """쿠팡 파트너스 CEA HMAC 서명 헤더 생성."""
    path, _, query = path_with_query.partition("?")
    signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = signed_date + method + path + query
    signature = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={signed_date}, signature={signature}"
    )


@dataclass
class PartnersClient:
    """쿠팡 파트너스 Open API 최소 클라이언트 (stdlib 만 사용)."""

    access_key: str
    secret_key: str
    sub_id: str = ""          # 채널 구분용 subId (예: "threads")
    timeout: int = 30

    @classmethod
    def from_env(cls, sub_id: str = "") -> Optional["PartnersClient"]:
        access = os.environ.get("COUPANG_ACCESS_KEY", "").strip()
        secret = os.environ.get("COUPANG_SECRET_KEY", "").strip()
        if not access or not secret:
            return None
        return cls(access_key=access, secret_key=secret,
                   sub_id=sub_id or os.environ.get("COUPANG_SUB_ID", "").strip())

    def _request(self, method: str, path_with_query: str, body: Optional[dict] = None) -> dict:
        url = DOMAIN + path_with_query
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", _hmac_authorization(method, path_with_query,
                                                            self.access_key, self.secret_key))
        req.add_header("Content-Type", "application/json;charset=UTF-8")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise CoupangError(f"쿠팡 파트너스 API 오류 {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CoupangError(f"쿠팡 파트너스 API 연결 실패: {exc.reason}") from exc

        if str(payload.get("rCode", "0")) not in ("0", "200"):
            raise CoupangError(f"쿠팡 파트너스 API 응답 오류: {payload.get('rMessage')}")
        return payload

    def search(self, keyword: str, limit: int = 5) -> List[CoupangProduct]:
        """검색어로 상품 조회. productUrl 은 이미 내 파트너스 추적이 붙은 링크."""
        query = urllib.parse.urlencode({"keyword": keyword, "limit": max(1, min(limit, 50))})
        if self.sub_id:
            query += "&" + urllib.parse.urlencode({"subId": self.sub_id})
        payload = self._request("GET", f"{SEARCH_PATH}?{query}")
        data = payload.get("data") or {}
        items = data.get("productData") if isinstance(data, dict) else data
        return [_from_partners(item) for item in (items or [])]

    def deeplink(self, coupang_urls: Sequence[str]) -> Dict[str, str]:
        """일반 쿠팡 URL → 내 파트너스 링크 (원본 URL → 단축 링크 매핑)."""
        path = DEEPLINK_PATH
        if self.sub_id:
            path += "?" + urllib.parse.urlencode({"subId": self.sub_id})
        payload = self._request("POST", path, {"coupangUrls": list(coupang_urls)})
        out: Dict[str, str] = {}
        for row in payload.get("data") or []:
            original = row.get("originalUrl") or ""
            out[original] = row.get("shortenUrl") or row.get("landingUrl") or ""
        return out

    def goldbox(self, limit: int = 20) -> List[CoupangProduct]:
        """골드박스(매일 특가) — 소재 발굴용."""
        payload = self._request("GET", GOLDBOX_PATH)
        return [_from_partners(item) for item in (payload.get("data") or [])][:limit]

    def best_category(self, category_id: int, limit: int = 20) -> List[CoupangProduct]:
        query = urllib.parse.urlencode({"limit": max(1, min(limit, 100))})
        path = BESTCATEGORY_PATH.format(cid=category_id) + "?" + query
        payload = self._request("GET", path)
        return [_from_partners(item) for item in (payload.get("data") or [])]


def _from_partners(item: dict) -> CoupangProduct:
    return CoupangProduct(
        name=str(item.get("productName") or ""),
        url=str(item.get("productUrl") or ""),
        price=_int_or_none(item.get("productPrice")),
        image=str(item.get("productImage") or ""),
        product_id=str(item.get("productId") or ""),
        category=str(item.get("categoryName") or ""),
        is_rocket=bool(item.get("isRocket")),
        is_free_shipping=bool(item.get("isFreeShipping")),
        affiliate=True,
        source="partners",
    )


def _int_or_none(value: object) -> Optional[int]:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


# --- Apify 폴백 (키 없이 판매 여부만 확인) --------------------------------
def search_via_apify(
    keywords: Sequence[str],
    *,
    token: str,
    max_per_keyword: int = 5,
    actor: str = COUPANG_SEARCH_ACTOR,
) -> Dict[str, List[CoupangProduct]]:
    """Apify 쿠팡 검색 액터로 키워드별 상품 조회 (제휴 링크 없음)."""
    from .collect import run_actor  # 지연 임포트(순환 방지)

    if not keywords:
        return {}
    items = run_actor(
        actor,
        {
            "keywords": list(keywords),
            "maxProductsPerKeyword": max_per_keyword,
            "includeDetail": False,
        },
        token=token,
    )
    grouped: Dict[str, List[CoupangProduct]] = {kw: [] for kw in keywords}
    for item in items:
        kw = str(item.get("keyword") or item.get("searchKeyword") or "")
        product = CoupangProduct(
            name=str(item.get("name") or item.get("productName") or item.get("title") or ""),
            url=str(item.get("url") or item.get("productUrl") or item.get("link") or ""),
            price=_int_or_none(item.get("price") or item.get("salePrice") or item.get("productPrice")),
            image=str(item.get("image") or item.get("imageUrl") or ""),
            product_id=str(item.get("productId") or item.get("id") or ""),
            category=str(item.get("category") or item.get("categoryName") or ""),
            is_rocket=bool(item.get("isRocket") or item.get("rocketDelivery")),
            rating=_float_or_none(item.get("rating") or item.get("ratingAverage")),
            review_count=_int_or_none(item.get("reviewCount") or item.get("ratingCount")),
            affiliate=False,
            source="apify",
        )
        bucket = grouped.get(kw)
        if bucket is None:
            bucket = grouped.setdefault(kw or (keywords[0] if keywords else ""), [])
        bucket.append(product)
    return grouped


def _float_or_none(value: object) -> Optional[float]:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


# --- 매칭 ---------------------------------------------------------------
def match_score(keyword: str, product_name: str) -> float:
    """검색어 토큰이 상품명에 얼마나 포함되는가 (0~1)."""
    kw_tokens = [t.lower() for t in _TOKEN_RE.findall(keyword) if len(t) > 1]
    if not kw_tokens:
        return 0.0
    name = product_name.lower()
    hits = sum(1 for t in kw_tokens if t in name)
    return hits / len(kw_tokens)


def pick_best(
    keyword: str,
    products: Iterable[CoupangProduct],
    *,
    min_match: float = 0.5,
) -> Optional[CoupangProduct]:
    """검색 결과 중 가장 잘 맞는 상품 하나. 로켓배송·리뷰 많은 쪽에 가산점."""
    ranked: List[tuple[float, CoupangProduct]] = []
    for product in products:
        base = match_score(keyword, product.name)
        if base < min_match:
            continue
        bonus = 0.05 if product.is_rocket else 0.0
        if (product.review_count or 0) >= 100:
            bonus += 0.05
        product.match_score = base
        ranked.append((base + bonus, product))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked[0][1]


@dataclass
class CoupangMatch:
    """게시물 ↔ 쿠팡 상품 매칭 결과."""

    post_url: str
    keyword: str
    found: bool
    product: Optional[CoupangProduct] = None
    alternatives: List[CoupangProduct] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "post_url": self.post_url,
            "keyword": self.keyword,
            "found": self.found,
            "product": self.product.to_dict() if self.product else None,
            "alternatives": [p.to_dict() for p in self.alternatives],
            "note": self.note,
        }
