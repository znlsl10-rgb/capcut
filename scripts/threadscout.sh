#!/usr/bin/env bash
# 해외 스레드 분석기(threadscout) — 원클릭 실행
#
#   ./scripts/threadscout.sh web                                  # 웹 UI (http://127.0.0.1:8010)
#   ./scripts/threadscout.sh scan --preset beauty --top 30        # 뷰티/헬스 주제 분석
#   ./scripts/threadscout.sh scan -k "air fryer" --top 20         # 키워드 직접 지정
#   ./scripts/threadscout.sh coupang "선크림"                      # 쿠팡 판매 확인
#   ./scripts/threadscout.sh presets                              # 키워드 프리셋 목록
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  echo "[setup] 가상환경 생성…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[setup] 의존성 확인…"
python -m pip install -q --upgrade pip
python -m pip install -q fastapi uvicorn openpyxl deep-translator

: "${APIFY_TOKEN:=}"
if [ -z "$APIFY_TOKEN" ]; then
  echo "⚠️  APIFY_TOKEN 이 없습니다 (수집 불가 — 저장된 JSON 재분석만 가능)"
  echo "    export APIFY_TOKEN=apify_api_..."
fi

if [ "${1:-}" = "web" ]; then
  shift
  exec python -m threadscout.web "$@"
fi

exec python -m threadscout "$@"
