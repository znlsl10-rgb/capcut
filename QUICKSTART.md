# 빠른 시작 (로컬 실행)

내 PC에서 실제 캡컷 초안을 만드는 가장 쉬운 방법입니다.

## 0. 준비물

- **Python 3.9+**
- **ffmpeg** (오디오 디코딩)
  - macOS: `brew install ffmpeg`
  - Windows: [gyan.dev 빌드](https://www.gyan.dev/ffmpeg/builds/) 설치 후 PATH 추가
  - Ubuntu: `sudo apt install ffmpeg`
- **캡컷 데스크톱** (초안을 한 번이라도 저장해 폴더가 생성돼 있어야 자동 감지됨)

## 1. 소재 준비

작업 폴더에 이렇게 두면 편합니다:

```
myproject/
├─ Born to Win.mp3        # 노래 오디오
├─ clips/                 # 배경 클립 여러 개 (mp4/mov/jpg/png)
│   ├─ 01.mp4
│   ├─ 02.mp4
│   └─ ...
└─ Mindtrack.xlsx         # 곡별 정답 가사 엑셀
```

## 2. 실행

리포지토리 폴더에서:

**macOS / Linux**
```bash
./scripts/run.sh run \
  --audio "Born to Win.mp3" \
  --background-dir ./clips \
  --songbook Mindtrack.xlsx --song "Born to Win"
```

**Windows**
```bat
scripts\run.bat run ^
  --audio "Born to Win.mp3" ^
  --background-dir .\clips ^
  --songbook Mindtrack.xlsx --song "Born to Win"
```

- `--draft-folder` 는 **생략**하면 캡컷 초안 폴더를 자동으로 찾습니다.
  못 찾으면 `run.sh detect` (또는 `run.bat detect`)로 확인 후 `--draft-folder` 로 지정하세요.
- `--style` 을 생략하면 곡 **무드**로 스타일이 자동 선택됩니다(각성→goosebump 등).

## 3. 캡컷에서 열기

실행이 끝나면 캡컷을 (재)시작하세요. **초안 목록**에 프로젝트가 나타납니다.
확인 후 **내보내기(Export)** 하면 완성입니다.

## 자주 쓰는 옵션

```bash
# 계획만 미리보기(초안 생성 X)
./scripts/run.sh run --audio song.mp3 --background-dir ./clips --dry-run

# 스타일 강제 지정
--style energetic            # goosebump / energetic / dreamy / retro

# 클립을 무작위로 배치
--clip-order shuffle

# 애드립/백보컬 (…) 줄 자막에서 제외
--no-adlibs

# 정답 가사를 엑셀 대신 텍스트 파일로
--lyrics-file lyrics.txt

# 초안 폴더 위치 확인 / 스타일 목록
./scripts/run.sh detect
./scripts/run.sh styles
```

## 문제 해결

- **"캡컷 초안 폴더를 찾지 못했습니다"** → 캡컷에서 새 프로젝트를 한 번 만들어 폴더를 생성한 뒤 `detect` 로 확인.
- **가사 타이밍이 어긋남** → `--whisper-model medium` 또는 `large-v3` 로 정확도를 높이거나, 결과 SRT를 손봐 `--lyrics-srt` 로 재사용.
- **소재가 안 보임(캡컷에서 빨간 화면)** → 초안 생성 후 원본 파일을 옮기지 마세요(절대경로 참조).
