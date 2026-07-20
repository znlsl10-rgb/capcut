# 🎬 CapCut Auto-Edit Agent

노래에 맞춰 **소름돋는 화면 전환**과 **가사 자막**을 자동으로 만들어
**캡컷(CapCut / 剪映) 초안 프로젝트**로 출력하는 에이전트입니다.

노래 파일과 배경(영상/이미지) 하나만 넣으면:

1. 🥁 노래의 **비트·드롭**을 분석해 그 지점마다 화면 전환(줌 펀치·섬광·글리치)을 배치하고,
2. 🎤 **Whisper**로 가사를 받아써 타임스탬프 자막을 얹고,
3. 📦 캡컷에서 바로 열 수 있는 **초안(`draft_content.json`)** 을 만들어 줍니다.

만들어진 초안을 캡컷에서 열어 확인한 뒤 **내보내기(export)** 만 하면 끝입니다.

> 캡컷은 공식 편집 API가 없어, 자동 편집은 **초안 프로젝트 파일을 직접 생성**하는
> 방식으로 동작합니다. draft 생성은 오픈소스 [`pyJianYingDraft`](https://pypi.org/project/pyJianYingDraft/) 를 사용합니다.

---

## ✨ 특징

- **비트 동기 전환** — librosa 로 비트/온셋/타악 에너지를 분석, 드롭 구간은 더 강렬한 전환.
- **가사 자동 자막** — faster-whisper(또는 openai-whisper) 받아쓰기 → 자막 트랙 + 입장 애니.
- **스타일 프리셋** — `goosebump`(소름) · `energetic`(강렬) · `dreamy`(잔잔) · `retro`(레트로).
- **영상/이미지 모두 지원** — 배경이 짧으면 자동 루프, 세로 비율은 블러 배경으로 채움.
- **드라이런** — 무거운 초안 생성 없이 편집 계획만 미리보기.

---

## 📦 설치

```bash
git clone <this-repo>
cd capcut
python -m pip install -r requirements.txt
```

추가로 필요한 것:

- **ffmpeg** — Whisper/librosa 오디오 디코딩용. (`brew install ffmpeg` / `apt install ffmpeg` / [윈도우 빌드](https://www.gyan.dev/ffmpeg/builds/))
- **MediaInfo** — pyJianYingDraft 가 소재 길이/해상도를 읽는 데 사용. 대부분 `pymediainfo` 설치 시 함께 동작하지만, 안 되면 [MediaInfo](https://mediaarea.net/en/MediaInfo) 를 설치하세요.

> GPU가 있으면 `capcut_agent/lyrics.py` 의 `device="auto"` 가 자동으로 CUDA를 사용해 받아쓰기가 훨씬 빨라집니다.

---

## 🚀 사용법

### 1) 설정 파일로 실행 (권장)

`examples/config.example.yaml` 을 복사해 경로를 채운 뒤:

```bash
python -m capcut_agent run --config config.yaml
```

### 2) 인자로 바로 실행

```bash
python -m capcut_agent run \
  --audio song.mp3 \
  --background bg.mp4 \
  --draft-folder "~/Movies/CapCut/User Data/Projects/com.lveditor.draft" \
  --name my_lyric_video \
  --style goosebump \
  --language ko
```

### 3) 계획만 미리보기 (초안 생성 X)

```bash
python -m capcut_agent run --config config.yaml --dry-run
```

### 4) 스타일 목록

```bash
python -m capcut_agent styles
```

---

## 📁 캡컷 초안 폴더 위치

`--draft-folder` 에는 캡컷이 초안을 저장하는 폴더를 지정합니다:

| OS | 경로 |
|----|------|
| Windows | `C:\Users\<이름>\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft` |
| macOS | `~/Movies/CapCut/User Data/Projects/com.lveditor.draft` |
| 중국판 剪映 | 위 경로의 `CapCut` → `JianyingPro` |

실행 후 캡컷을 (재)시작하면 **초안 목록**에 생성된 프로젝트가 나타납니다.

> 캡컷 버전에 따라 초안 포맷이 다를 수 있습니다. 잘 열리는 캡컷 버전은
> `pyJianYingDraft` 문서를 참고하세요. 초안을 열 때 캡컷은 자동으로 최신
> 포맷으로 변환합니다.

---

## 🧠 동작 원리

```
              ┌─────────────────────┐
  노래 오디오 ─┤ audio.py            │  librosa: 비트·온셋·타악 에너지
              │  → BeatMap          │  → 전환 지점 + 강박(드롭) 표시
              └─────────┬───────────┘
                        │
              ┌─────────▼───────────┐
              │ transitions.py      │  스타일 프리셋: 어떤 전환/애니를
              │  → 전환/애니 선택    │  언제 쓸지 결정 (드롭엔 섬광/글리치)
              └─────────┬───────────┘
                        │
  노래 오디오 ─┐        │
              │ ┌───────▼───────────┐
              └─┤ lyrics.py         │  Whisper: 가사 + 타임스탬프
                │  → LyricSegment[] │  → SRT 저장
                └───────┬───────────┘
                        │
              ┌─────────▼───────────┐
              │ draft_builder.py    │  pyJianYingDraft:
              │  → draft_content.json│  배경컷+전환+자막+오디오 트랙 생성
              └─────────────────────┘
```

- **배경 트랙**: 전환 지점마다 배경을 컷으로 나누고, 각 컷에 줌 입장 애니와
  다음 컷으로의 전환을 붙입니다. 드롭 구간은 강렬한 전환 + 화면 효과로 강조.
- **자막 트랙**: 가사 세그먼트마다 텍스트 + 입장 애니(팝/타자기 등).
- **오디오 트랙**: 노래 원본.

각 모듈은 **무거운 의존성을 지연 임포트**하도록 분리되어 있어, 순수 로직
(비트 선정 · SRT 생성 · 프리셋 · 계획 요약)은 라이브러리 없이 테스트됩니다.

---

## 🎨 스타일 커스터마이징

`capcut_agent/transitions.py` 의 `PRESETS` 에서 전환/애니 목록, 자막 색/크기,
전환 길이를 바꿀 수 있습니다. 전환·효과 이름은 캡컷 내 효과명(중국어 원문)과
동일합니다. 새 프리셋을 추가하면 `--style <이름>` 으로 바로 사용됩니다.

---

## 🧪 테스트

```bash
python -m pytest -q
```

순수 로직 테스트는 librosa/whisper/pyJianYingDraft 없이 실행됩니다.

---

## ⚠️ 참고

- Whisper 받아쓰기는 노래(보컬+반주)에서 오차가 생길 수 있습니다. 결과 SRT를
  손보거나(`--output-srt`), 미리 만든 SRT를 `--lyrics-srt` 로 넣으면 정확합니다.
- 생성된 초안은 **원본 미디어 파일 경로를 참조**합니다. 편집 중 파일을 옮기지 마세요.
- 상업적 사용 시 노래/영상의 저작권을 반드시 확인하세요.
