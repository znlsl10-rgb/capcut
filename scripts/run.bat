@echo off
REM 캡컷 자동 편집 에이전트 — Windows 원클릭 실행
REM
REM 사용 예:
REM   scripts\run.bat run --audio "Born to Win.mp3" --background-dir .\clips ^
REM       --songbook Mindtrack.xlsx --song "Born to Win"
REM   (--draft-folder 생략 시 캡컷 초안 폴더 자동 감지)
REM
REM   scripts\run.bat detect     초안 폴더 위치 확인
REM   scripts\run.bat styles     스타일 목록
setlocal
cd /d "%~dp0.."

REM 1) 가상환경 준비
if not exist ".venv" (
  echo [setup] 가상환경 생성...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

REM 2) 의존성 설치
echo [setup] 의존성 설치 확인...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

REM 3) ffmpeg 확인
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [!] ffmpeg 가 없습니다. https://www.gyan.dev/ffmpeg/builds/ 에서 설치 후 PATH 에 추가하세요.
)

REM 4) 실행
echo [run] python -m capcut_agent %*
python -m capcut_agent %*

endlocal
