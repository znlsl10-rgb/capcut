@echo off
REM 해외 스레드 분석기(threadscout) — Windows 원클릭 실행
REM
REM 사용 예:
REM   set APIFY_TOKEN=apify_api_xxxxx
REM   scripts\threadscout.bat scan --preset beauty --max-posts 40 --days 45 --top 30 --save-raw output\raw.json
REM   scripts\threadscout.bat web                       웹 UI (http://127.0.0.1:8010)
REM   scripts\threadscout.bat coupang "선크림"           쿠팡 판매 확인
REM   scripts\threadscout.bat presets                   키워드 프리셋 목록
setlocal
cd /d "%~dp0.."

REM 1) 가상환경 준비
if not exist ".venv" (
  echo [setup] 가상환경 생성...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

REM 2) 의존성 설치 (웹 UI / 엑셀 보드 / 자동 번역)
echo [setup] 의존성 설치 확인...
python -m pip install -q --upgrade pip
python -m pip install -q fastapi uvicorn openpyxl deep-translator

REM 3) 토큰 확인
if "%APIFY_TOKEN%"=="" (
  echo [!] APIFY_TOKEN 이 없습니다. 수집하려면 먼저 설정하세요:
  echo     set APIFY_TOKEN=apify_api_xxxxx
  echo     ^(토큰 발급: https://console.apify.com/settings/integrations^)
)

REM 4) 실행
if "%~1"=="web" (
  shift
  echo [run] python -m threadscout.web
  python -m threadscout.web
  goto :end
)

echo [run] python -m threadscout %*
python -m threadscout %*

:end
endlocal
