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

## ✨ 특징

- **참고 영상 벤치마킹** — 잘 만든 영상을 하나 주면 **컷 편집 속도 · 음악 템포 ·
  자막 위치 · 화면 비율**을 분석해, 내 로컬 클립으로 **유사한 느낌**의 영상을
  자동 편집합니다. (아래 "참고 영상 벤치마킹" 섹션)
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

## 🔬 참고 영상 벤치마킹 (내 영상으로 유사하게)

잘 만든 **참고 영상**을 하나 주면, 그 영상의 **편집 레시피**(컷 편집 속도 ·
음악 템포 · 자막 위치 · 화면 비율)를 분석해 **내 로컬 클립**으로 유사한 느낌의
영상을 자동 편집합니다. 벤치마킹하는 3요소는 요청하신 **자막 · 음악 · 컷편집**
그대로입니다.

동작 순서:

1. **분석** — `ffmpeg` 장면 전환 감지로 컷 리듬(분당 컷 수·컷 길이)을 재고,
   오디오 템포(BPM)를 측정하며, 프레임을 샘플링해 자막 밴드의 세로 위치를
   추정합니다. 해상도/비율도 읽습니다.
2. **벤치마크** — 분석값으로 **스타일 프리셋 · 전환 간격 · 소재 모드 · 출력
   해상도 · 자막 높이**를 자동 결정합니다.
3. **적용** — 내 클립 + 음악(내 곡 또는 참고 영상 오디오)으로 캡컷 초안을
   만듭니다. 컷은 내 음악의 비트에 놓이되 **참고 영상만큼 촘촘하게/성글게** 끊고,
   자막은 참고 영상과 **같은 높이**에 놓입니다.

### 분석만 (편집 레시피 미리보기)

```bash
python -m capcut_agent analyze --reference ref.mp4 --out profile.json
```

출력 예:

```
🔬 참고 영상 분석 — ref.mp4
   포맷    1080x1920 · 세로 · 30fps · 28.4s  · 오디오 있음
   음악    ~140 BPM
   컷편집  46컷 · 분당 97.2컷 · 컷 길이 중앙값 0.58s (최단 0.20s)
   자막    하단 밴드 (세로 0.86 · 대비 3.4x)
   ⇒ 벤치마크 스타일 'energetic' · 전환간격 ~0.49s · 소재모드 beat
```

### 유튜브 링크로 벤치마킹 + 대본 자막

`--reference` 에 **유튜브/웹 링크**를 넣으면 영상을 내려받아(yt-dlp) 분석하고,
`--script` 로 **내 대본 텍스트**를 주면 그 대본을 **비트에 맞춰 자막**으로 얹습니다.
즉 "유튜브 링크 + 내 폴더의 영상/이미지 + 대본" → 유사한 내 영상이 됩니다.

```bash
python -m capcut_agent benchmark \
  --reference "https://youtu.be/VIDEO_ID" \
  --background-dir ./myclips \
  --audio mysong.mp3 \
  --script script.txt
```

- `--script` 를 주면 Whisper 받아쓰기 대신 대본을 사용합니다(정확·빠름).
- 링크 다운로드에는 **yt-dlp** 가 필요합니다: `pip install yt-dlp`.

### 벤치마킹해서 내 영상 만들기

```bash
# 내 곡을 사운드트랙으로
python -m capcut_agent benchmark \
  --reference ref.mp4 \
  --background-dir ./myclips \
  --audio mysong.mp3 \
  --draft-folder "~/Movies/CapCut/User Data/Projects/com.lveditor.draft"

# 참고 영상의 오디오를 그대로 음악으로 사용
python -m capcut_agent benchmark \
  --reference ref.mp4 --background-dir ./myclips --use-reference-audio

# 스타일만 직접 지정(나머지는 참고 영상에서 자동)
python -m capcut_agent benchmark --reference ref.mp4 \
  --background-dir ./myclips --audio mysong.mp3 --style goosebump --dry-run
```

자막은 사운드트랙을 Whisper 로 받아써 채웁니다. 정답 가사(`--songbook`/`--song`,
`--lyrics-file`), 영한 이중 자막(`--lyrics-ko`/`--translate`) 옵션은 `run` 과
동일하게 쓸 수 있습니다.

> 분석에는 **ffmpeg/ffprobe** 가 필요합니다(장면 전환 감지·오디오/프레임 추출).
> 템포·자막 추정은 부가 정보라 실패해도 나머지는 그대로 진행합니다
> (`--no-music` / `--no-subtitles` 로 생략해 빠르게 돌릴 수 있어요).

---

## 🤖 AI 소재 "최소 제작" (적게 만들어 슬로우로 채우기)

배경 footage 를 **AI(예: 힉스필드)로 최소 개수만 생성**하고, 남는 길이는
**슬로우(커버리지 모드)로 늘려** 곡 전체를 채우는 전략입니다. 동일한 차·배경·
분위기의 짧은 클립 몇 개만 있으면, 비트 컷·엑셀 자막이 얹혀 뮤직비디오가 됩니다.

**필요한 최소 클립 수**는 곡 길이·클립 길이·슬로우 한도로 계산합니다:

```bash
python -m capcut_agent genplan --song-duration 100 --clip-len 5 --slow-floor 0.5
# → 클립 1개가 10.0s 를 덮음 → 최소 10개 생성 → 0.50x(2배 슬로우)로 곡을 채움
```

계산된 개수만큼 AI 클립을 만들어 한 폴더에 모은 뒤, 그 폴더로 초안을 만듭니다
(커버리지 모드가 자동으로 슬로우를 적용합니다):

```bash
python -m capcut_agent run \
  --audio mysong.mp3 --background-dir ./ai_clips \
  --footage-mode coverage --slow-floor 0.5 \
  --songbook Mindtrack.xlsx --song "곡명"
```

> AI 클립을 만들 때는 **한 영상 안에서 동일한 차·배경·분위기**가 유지되도록,
> 기준 이미지 1장을 만든 뒤 그 이미지를 **참조**로 걸어 카메라 움직임만 바꿔
> 여러 컷을 뽑는 방식을 권장합니다(identity/reference). 그러면 컷이 바뀌어도
> 같은 차·같은 도시가 유지됩니다.

### 촬영 리스트(shot recipe) — 통일감 + 다양성

`capcut_agent/shotlist.py` 는 **기준 이미지 1장**으로 만들 다양한 컷의 프롬프트
세트를 정해진 규칙으로 만들어 줍니다. 규칙(코드로 고정):

- 모든 컷은 **기준 이미지와 동일한 스타일·분위기·화질**로 통일(참조 접미사 자동 부착).
- **중간중간 1인칭 시점(POV)** 을 섞고, 1인칭엔 **자연스러운 손떨림**을 넣음.
- 피사체가 **차량**이면 **운전자 1인칭 시점**을 반드시 포함.
- 시네마틱 컷(establishing·orbit·트래킹·클로즈업·크레인)과 1인칭 컷을 번갈아 배치.

```python
from capcut_agent.shotlist import build_shots, summarize_shots
shots = build_shots("matte black sports car in a neon city at night",
                    is_vehicle=True, count=6, min_pov=2)
print(summarize_shots(shots))   # 각 컷 이름/유형
# shots[i]["prompt"] 를 이미지-투-비디오 생성기(예: 힉스필드 Seedance)에 그대로 전달
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
