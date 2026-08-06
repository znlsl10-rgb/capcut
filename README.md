# 🎬 CapCut Auto-Edit Agent

노래에 맞춰 **소름돋는 화면 전환**과 **가사 자막**을 자동으로 만들어
**캡컷(CapCut / 剪映) 초안 프로젝트**로 출력하는 에이전트입니다.

노래 파일과 배경(영상/이미지) 하나만 넣으면:

1. 🥁 노래의 **비트·드롭**을 분석해 그 지점마다 화면 전환(줌 펀치·섬광·글리치)을 배치하고,
2. 🎤 **Whisper**로 가사를 받아써 타임스탬프 자막을 얹고,
3. 📦 캡컷에서 바로 열 수 있는 **초안(`draft_content.json`)** 을 만들어 줍니다.

만들어진 초안을 캡컷에서 열어 확인한 뒤 **내보내기(export)** 만 하면 끝입니다.

> 캡컷은 공식 편집 API가 없어, 자동 편집은 **초안 프로젝트 파일을 직접 생성**하는
> 방식으로 동작합니다. draft 생성은 오픈소스 [`pyCapCut`](https://pypi.org/project/pyCapCut/) 를 사용합니다.

---

## 🚀 동기부여 쇼츠 에이전트 (`shorts/`)

성공 **동기부여 유튜브 채널의 구독자 성장**을 목표로, 내 소재를 편집해 **세로 쇼츠**를
만들고 **게시 메타데이터**까지 자동 생성하는 레이어입니다. 위 뮤직비디오 엔진을 그대로
재사용합니다 — *노래→나레이션, 가사→대본, 배경→내 소재* 로 매핑.

```bash
# 이번 주 주제 뽑기(결정론적 로테이션)
python -m shorts topics --days 7 --seed 2026-08

# 대본만으로 계획 + 게시 메타 미리보기(라이브러리 불필요)
python -m shorts plan --script examples/script.example.txt --channel examples/channel.example.yaml

# 나레이션 + 내 소재 + 대본 → 세로 캡컷 초안 + 메타/자막/게시 매니페스트
python -m shorts build \
  --script script.txt --channel channel.yaml \
  --narration voice.mp3 --footage-dir ./clips --name morning_routine
```

전체 파이프라인·자동화 경계·다음 단계는 **[`shorts/ROADMAP.md`](shorts/ROADMAP.md)** 참고.
채널 브랜딩은 [`examples/channel.example.yaml`](examples/channel.example.yaml) 하나만 채우면 됩니다.

---

## ✨ 특징

- **여러 클립 비트 배치** — 배경 클립 여러 개를 넣으면 **비트마다 다른 클립**으로
  전환되는 몽타주 생성(`sequential` 순환 / `shuffle` 무작위). 컷은 항상 감지된
  비트 시각에 놓여 **박자에 정확히** 맞습니다.
- **가사 구간 박자 강조** — 가사가 나오는 구간의 비트를 강박으로 승격해, 그
  "소름 포인트"에서 **더 강렬한 전환(섬광·글리치)을 짧고 타이트하게** 꽂습니다.
- **정답 가사 교정** — 정답 가사를 주면 Whisper 자동 자막이 틀려도 **정답으로 교정**합니다.
  텍스트는 정답, 타이밍은 Whisper 를 강제 정렬(forced-alignment)로 이식해, 오탈자·오인식
  없이 **정확한 가사가 정확한 타이밍에** 놓입니다. 반복 후렴도 한 줄도 잃지 않습니다.
  곡별 정답 가사는 **송북 엑셀**(곡명·무드·가사)로 관리하며, 무드로 스타일도 자동 선택됩니다.
- **비트 동기 전환** — librosa 로 비트/온셋/타악 에너지를 분석, 드롭 구간은 더 강렬한 전환.
- **가사 자동 자막** — faster-whisper(또는 openai-whisper) 받아쓰기 → 자막 트랙 + 입장 애니.
- **스타일 프리셋** — `goosebump`(소름) · `energetic`(강렬) · `dreamy`(잔잔) · `retro`(레트로).
- **영상/이미지 모두 지원** — 클립이 짧으면 자동 루프, 세로 비율은 블러 배경으로 채움.
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
- **MediaInfo** — pyCapCut 이 소재 길이/해상도를 읽는 데 사용. 대부분 `pymediainfo` 설치 시 함께 동작하지만, 안 되면 [MediaInfo](https://mediaarea.net/en/MediaInfo) 를 설치하세요.

> GPU가 있으면 `capcut_agent/lyrics.py` 의 `device="auto"` 가 자동으로 CUDA를 사용해 받아쓰기가 훨씬 빨라집니다.

---

## 🚀 사용법

> 💡 **가장 쉬운 로컬 실행은 [QUICKSTART.md](QUICKSTART.md) 참고** — `scripts/run.sh`(mac/Linux)
> 또는 `scripts\run.bat`(Windows)가 가상환경·의존성·초안폴더 자동 감지까지 처리합니다.
>
> ```bash
> ./scripts/run.sh run --audio "Born to Win.mp3" --background-dir ./clips \
>     --songbook Mindtrack.xlsx --song "Born to Win"
> ```
> `--draft-folder` 를 생략하면 캡컷 초안 폴더를 자동으로 찾습니다
> (`./scripts/run.sh detect` 로 위치 확인).

### 1) 설정 파일로 실행 (권장)

`examples/config.example.yaml` 을 복사해 경로를 채운 뒤:

```bash
python -m capcut_agent run --config config.yaml
```

### 2) 인자로 바로 실행

```bash
# 여러 배경 클립을 비트에 맞춰 순환 배치
python -m capcut_agent run \
  --audio song.mp3 \
  --background clip01.mp4 clip02.mp4 clip03.mp4 clip04.jpg \
  --clip-order shuffle \
  --draft-folder "~/Movies/CapCut/User Data/Projects/com.lveditor.draft" \
  --name my_lyric_video \
  --style goosebump \
  --language ko

# 정답 가사로 자동 자막 교정 (송북 엑셀 + 곡명 → 무드로 스타일 자동)
python -m capcut_agent run \
  --audio "Born to Win.mp3" --background-dir ./clips \
  --songbook Mindtrack.xlsx --song "Born to Win" \
  --draft-folder "~/Movies/CapCut/User Data/Projects/com.lveditor.draft"

# 폴더째로 넣기 (안의 영상/이미지를 이름순으로 모두 사용)
python -m capcut_agent run \
  --audio song.mp3 --background-dir ./clips \
  --draft-folder "~/Movies/CapCut/User Data/Projects/com.lveditor.draft"
```

### 정답 가사 교정 (Whisper 오인식 바로잡기)

노래 받아쓰기는 반주에 섞여 오탈자가 잦습니다. **정답 가사**를 주면 그 텍스트를
그대로 쓰고 Whisper 는 **타이밍만** 제공하도록 강제 정렬합니다.

```bash
# 1) 송북 엑셀 + 곡명 (무드로 스타일도 자동 선택)
--songbook Mindtrack.xlsx --song "Born to Win"

# 2) 가사 텍스트 파일
--lyrics-file lyrics.txt

# 3) 애드립/백보컬 (…) 줄 제외하고 싶으면
--no-adlibs
```

송북 엑셀은 `가사 원문` 시트(`곡명 | 분위기 | 파일 | 길이 | 공개 링크 | 가사 원문`)와
`분위기 가이드` 시트를 읽습니다. 무드(각성/버팀/확신/도약/도착/위로)는 스타일
프리셋과 배경 색감 가이드로 매핑됩니다.

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
> `pyCapCut` 문서를 참고하세요. 초안을 열 때 캡컷은 자동으로 최신
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
              │ draft_builder.py    │  pyCapCut:
              │  → draft_content.json│  배경컷+전환+자막+오디오 트랙 생성
              └─────────────────────┘
```

- **배경 트랙**: 비트 지점마다 컷을 나누고 **여러 클립을 순환/무작위로 배치**해
  컷마다 화면이 바뀌게 합니다. 각 컷엔 줌 입장 애니 + 다음 컷 전환을 붙입니다.
  컷 지점 = 비트 시각이므로 전환이 **박자에 정확히** 맞고, 가사·드롭 구간은
  더 짧고 강렬한 전환(섬광·글리치)으로 타격감을 줍니다.
  같은 클립을 다시 쓸 땐 재생 헤드를 앞으로 밀어 **다른 부분**을 보여줍니다.
- **자막 트랙**: 가사 세그먼트마다 텍스트 + 입장 애니(팝/타자기 등).
- **오디오 트랙**: 노래 원본.

각 모듈은 **무거운 의존성을 지연 임포트**하도록 분리되어 있어, 순수 로직
(비트 선정 · SRT 생성 · 프리셋 · 계획 요약)은 라이브러리 없이 테스트됩니다.

---

## 🎨 스타일 커스터마이징

`capcut_agent/transitions.py` 의 `PRESETS` 에서 전환/애니 목록, 자막 색/크기,
전환 길이를 바꿀 수 있습니다. 전환·효과 이름은 pyCapCut 의 enum 멤버명
(CapCut 글로벌 영어 효과명, 예: `Snap_Zoom`, `White_Flash`)과 동일합니다.
새 프리셋을 추가하면 `--style <이름>` 으로 바로 사용됩니다.

---

## 🧪 테스트

```bash
python -m pytest -q
```

순수 로직 테스트는 librosa/whisper/pyCapCut 없이 실행됩니다.

---

## ⚠️ 참고

- Whisper 받아쓰기는 노래(보컬+반주)에서 오차가 생길 수 있습니다. 결과 SRT를
  손보거나(`--output-srt`), 미리 만든 SRT를 `--lyrics-srt` 로 넣으면 정확합니다.
- 생성된 초안은 **원본 미디어 파일 경로를 참조**합니다. 편집 중 파일을 옮기지 마세요.
- 상업적 사용 시 노래/영상의 저작권을 반드시 확인하세요.
