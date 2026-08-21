# 🧵 threadscout — 해외 스레드 분석 → 쿠팡 파트너스 판매 글

**목적**: 해외 Threads에서 *노출 잘 되고 댓글·공유 많은 글*을 찾아 → 그 글이 미는 **제품이 쿠팡에 있는지 확인**하고 →
**쿠팡 파트너스 링크가 붙은 한국어 스레드 글 초안**까지 자동으로 만들어 준다.

```
키워드 → [수집] → [해외 글만 필터] → [노출·댓글·공유 점수] → [제품 추출]
      → [쿠팡 검색/파트너스 링크] → [한국어 초안(면책문구 포함)] → 리포트(MD/HTML/CSV/JSON)
```

---

## 1. 설치

```bash
pip install -r requirements.txt          # fastapi/uvicorn (웹 UI용)
pip install deep-translator              # 선택: 자동 번역 (없으면 원문 유지)
```

수집·분석 엔진 자체는 **표준 라이브러리만** 사용한다(추가 설치 불필요).

## 2. 토큰 설정

| 환경변수 | 용도 | 없을 때 |
|---|---|---|
| `APIFY_TOKEN` | Threads 수집 (Apify 액터) | 수집 불가 — 저장된 JSON 재분석만 가능 |
| `COUPANG_ACCESS_KEY` / `COUPANG_SECRET_KEY` | 쿠팡 파트너스 상품검색·딥링크 | Apify 쿠팡 액터로 *판매 여부만* 확인 (제휴 링크 X) |
| `COUPANG_SUB_ID` | 파트너스 채널 추적용 subId (기본 `threads`) | 생략 가능 |

```bash
export APIFY_TOKEN=apify_api_xxx
export COUPANG_ACCESS_KEY=xxx
export COUPANG_SECRET_KEY=xxx
```

- Apify 토큰: https://console.apify.com/settings/integrations
- 쿠팡 파트너스 Open API 키: 파트너스 → 내 정보 → Open API (승인 필요)

## 3. 실행

### 웹 UI (추천)

```bash
python -m threadscout.web          # → http://127.0.0.1:8010
```

키워드 입력 → 분석 시작 → 탭에서 **상위 글 / 공통 패턴 / 쿠팡 매칭 / 한국어 초안(복사 버튼)** 확인.

### CLI

```bash
# 수집 + 분석 + 쿠팡 매칭 + 초안
python -m threadscout scan -k "air fryer" -k "amazon finds" \
    --max-posts 80 --days 30 --top 20 --save-raw output/raw.json

# 저장한 원시 데이터로 재분석 (Apify 비용 0)
python -m threadscout scan --from-json output/raw.json --top 30

# 쿠팡 판매 여부 + 파트너스 링크만 확인
python -m threadscout coupang "에어프라이어" "무선청소기"

# 쿠팡 상품 URL → 내 파트너스 딥링크
python -m threadscout link https://www.coupang.com/vp/products/1234567

# 오늘의 골드박스 특가(소재 발굴)
python -m threadscout goldbox --limit 20

# 제품 사전에 등록된 쿠팡 검색어 목록
python -m threadscout terms
```

리포트는 `output/threadscout_<시각>.{md,html,csv,json}` 로 저장된다.

---

## 4. 점수 계산 방식

절대 수치(좋아요 1만)는 계정 크기·주제마다 의미가 달라서, **수집한 글들 안에서의 백분위**로 환산해 가중합한다(0~100점).

| 지표 | 뜻 | 기본 가중치 |
|---|---|---|
| exposure | 노출(조회수, 로그 스케일) | 0.25 |
| share_rate | (리포스트+인용+공유) / 노출 | 0.25 |
| reply_rate | 댓글 / 노출 | 0.25 |
| reach | 노출 / 팔로워 — 작은 계정이 크게 터진 글 | 0.15 |
| velocity | 노출 / 경과시간 — 지금 퍼지는 중인 글 | 0.10 |

가중치는 CLI 옵션으로 바꿀 수 있다: `--w-share 0.4 --w-reply 0.3 --w-exposure 0.2 ...`
(합이 1이 아니어도 자동 정규화)

조회수를 주지 않는 액터를 쓰면 **좋아요 → 노출 추정치**(풀에서 실측한 중앙 비율)로 계산하고,
리포트에 추정 비율을 표시한다.

## 5. 분석 항목

- **훅(첫 줄) 유형별 성과** — 질문형 / 숫자형 / 리스트형 / 논쟁형 / 방법형 / 스토리형 / 댓글유도형
- **글 길이·미디어 유무·발행 시간대(KST)** 별 평균 점수와 배수(lift)
- **상위권에서 유독 많이 나온 단어·해시태그** (lift = 상위 등장률 ÷ 하위 등장률)
- **벤치마킹할 계정** — 평균 점수 높은 계정과 대표 글

## 6. 쿠팡 매칭

1. 상위 글 텍스트에서 **커머스 의도**(구매/추천/가격/링크 신호)를 점수화
2. 제품 카테고리 사전(영→한, 150여 개)과 브랜드형 고유명사로 **쿠팡 검색어** 생성
   (예: `I bought the Ninja air fryer` → `Ninja 에어프라이어`, `에어프라이어`)
3. 파트너스 API(또는 Apify)로 검색 → 상품명 토큰 일치도로 최적 상품 선택
4. 가격 × 카테고리 수수료율로 **건당 예상 수익** 추정 (요율은 변동되므로 참고용)

사전에 없는 카테고리를 밀고 싶으면 `threadscout/product.py` 의 `PRODUCT_LEXICON` 에 한 줄 추가하면 된다.

## 7. 한국어 초안

원문 훅 유형을 그대로 살린 한국어 훅 + 번역 본문(짧은 줄 재배치) + 상품/링크 + 댓글 유도 + 해시태그 +
**쿠팡 파트너스 대가성 문구**(자동 삽입, 법적 필수)로 구성된다.

```text
에어프라이어 사기 전에 이거 하나만 보세요

에어프라이어 하나 샀는데 주방이 완전히 바뀌었어요.
기름 없이 튀김이 되니까 설거지가 반으로 줄었습니다.

🛒 쿠쿠 에어프라이어 5L · 79,000원 · 로켓배송
👉 https://link.coupang.com/a/xxxx

여러분은 어떤 거 쓰세요? 댓글로 알려주세요 👇
#에어프라이어 #로켓배송 #쿠팡추천

이 게시물은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.
```

> ⚠️ 초안은 **그대로 복붙하지 말고 본인 말투로 고쳐 쓰는 걸 권장**한다.
> 번역문 그대로 올리면 중복 콘텐츠로 노출이 깎일 수 있고, 원문 작성자의 저작물을 그대로 옮기는 문제도 생긴다.
> 아이디어·구조(훅/포맷/각도)를 참고하는 용도로 쓰는 것이 안전하다.

## 8. 지켜야 할 것

- 쿠팡 파트너스 링크가 들어간 글에는 **대가성 문구 고지 필수** (표시광고법·파트너스 이용약관)
- 제품을 써보지 않았다면 **써봤다고 쓰지 말 것** (허위·과장 광고)
- 수집은 **공개 게시물**만 대상으로 하며, 각 플랫폼의 이용약관과 로봇 정책을 확인할 책임은 사용자에게 있다
- 수수료율·정책은 쿠팡 파트너스 공지에 따라 바뀐다 — 리포트의 수익 추정치는 참고용

## 9. 모듈 구성

| 파일 | 역할 |
|---|---|
| `models.py` | 스크레이퍼별 필드명 차이 흡수 → `ThreadPost` 정규화 |
| `collect.py` | Apify 액터 실행/데이터셋 수집, 로컬 JSON 로드·저장 |
| `score.py` | 필터 + 지표 계산 + 백분위 가중합 점수 |
| `analyze.py` | 훅/길이/미디어/시간대/키워드/계정 패턴 분석 |
| `product.py` | 커머스 의도 판정 + 제품 추출 + 쿠팡 검색어 생성 |
| `coupang.py` | 파트너스 Open API(HMAC) · Apify 폴백 · 상품 매칭 |
| `draft.py` | 번역 + 한국어 스레드 초안 생성 |
| `pipeline.py` | 전체 파이프라인 (CLI·웹 공용) |
| `report.py` | MD / HTML / CSV / JSON 리포트 |
| `cli.py` / `web.py` / `webapp.py` | CLI, 로컬 웹 서버, FastAPI 앱 |

## 10. 테스트

```bash
python -m pytest tests/test_threadscout.py tests/test_threadscout_webapp.py -q
```

네트워크·Apify·쿠팡 API 없이 순수 로직만으로 돌아간다.
