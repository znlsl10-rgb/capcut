#!/usr/bin/env bash
# 캡컷 자동 편집 에이전트 — macOS/Linux 원클릭 실행
#
# 사용 예:
#   ./scripts/run.sh run --audio "Born to Win.mp3" --background-dir ./clips \
#       --songbook Mindtrack.xlsx --song "Born to Win"
#   (--draft-folder 생략 시 캡컷 초안 폴더 자동 감지)
#
#   ./scripts/run.sh detect          # 초안 폴더 위치 확인
#   ./scripts/run.sh styles          # 스타일 목록
set -euo pipefail

cd "$(dirname "$0")/.."

# 1) 가상환경 준비
if [ ! -d ".venv" ]; then
  echo "[setup] 가상환경 생성…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 2) 의존성 설치(최초 1회는 시간이 걸립니다)
echo "[setup] 의존성 설치 확인…"
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

# 3) ffmpeg 확인(오디오 디코딩에 필요)
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠️  ffmpeg 가 없습니다. 오디오 디코딩에 필요합니다."
  echo "    macOS:  brew install ffmpeg"
  echo "    Ubuntu: sudo apt install ffmpeg"
fi

# 4) 실행 (인자 그대로 전달)
echo "[run] python -m capcut_agent $*"
python -m capcut_agent "$@"
