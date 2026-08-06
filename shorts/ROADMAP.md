# 🚀 동기부여 쇼츠 에이전트 — 로드맵

성공 동기부여 유튜브 채널의 **구독자 성장**을 목표로, 내 소재를 편집해 세로 쇼츠를
만들고 게시까지 자동화하는 에이전트. 기존 CapCut 편집 엔진(`capcut_agent`)을 재사용합니다.

## 전체 파이프라인

```
 ①주제        ②대본         ③나레이션        ④편집(캡컷)         ⑤내보내기       ⑥게시
 topics   →   script   →   narration   →   build draft   →   export mp4  →  publish
 (자동)       (반자동)      (내 목소리/TTS)   (자동, 세로)        (캡컷 1클릭)     (반자동)
```

**선택된 방향: B(ffmpeg 헤드리스 렌더) + 틱톡 우선 + TTS 자동생성.**

| 단계 | 상태 | 구현 |
|------|------|------|
| ① 주제 발굴·로테이션 | ✅ 완료 | `topics.py` — 결정론적 주제 뱅크 + 콘텐츠 캘린더 |
| ② 대본 구조화(훅/본문/CTA) | ✅ 완료 | `script.py` — 파싱 + 쇼츠용 짧은 자막 분할 |
| ②' 게시 메타(제목/설명/해시태그) | ✅ 완료 | `metadata.py` — 유튜브/틱톡 |
| ③ 나레이션 음성(TTS) | 🔶 시임 | `voice.py` — 내 목소리 또는 higgsfield `generate_audio` |
| ④ 헤드리스 mp4 렌더(컷+한글자막) | ✅ 완료 | `render.py` — ffmpeg, 캡컷 없이 완성 mp4 |
| ④' 캡컷 초안(손보기용, 선택) | ✅ 완료 | `pipeline.py --make-draft` → 기존 `build_draft` |
| ⑤ 완성 mp4 | ✅ 완료 | `build` 가 `*.mp4` 직접 출력(무인) |
| ⑥ 틱톡 업로드 | 🔶 연결 | `publish.py` 매니페스트 → higgsfield `tiktok_publish` |
| ⑥' 유튜브 업로드 | ⛳ 나중 | YouTube Data API v3(OAuth) — 자격증명 필요 |

## 지금 바로 쓸 수 있는 것

```bash
# 이번 주 주제 뽑기
python -m shorts topics --days 7 --seed 2026-08

# 대본만으로 계획 + 게시 메타 미리보기(라이브러리 불필요)
python -m shorts plan --script script.txt --channel examples/channel.example.yaml

# 나레이션 + 내 소재 + 대본 → 완성 mp4 + 자막 + 게시 매니페스트 (헤드리스, 무인)
python -m shorts build \
  --script script.txt --channel channel.yaml \
  --narration voice.mp3 --footage-dir ./clips --name morning_routine

#  ↳ Whisper 없이 돌리려면 --no-align (나레이션 길이에 비례해 자막 분배)
#  ↳ 캡컷 초안도 같이 뽑으려면 --make-draft
```

산출물:
- `*.mp4` — **완성된 세로 쇼츠**(내 소재 컷 + 굵은 한글 자막 + 나레이션). 바로 업로드 가능
- `*.metadata.json` — 유튜브/틱톡 제목·설명·해시태그·검색태그
- `*.srt` — 자막
- `*.publish.json` — 게시 매니페스트(`status: ready_to_upload`)

## 렌더러(`render.py`) 특징

- 나레이션 길이에 맞춰 **자막 경계에서 컷** → 말과 화면이 함께 전환
- 내 소재를 세로 **1080×1920 cover-crop**(가로 영상도 꽉 채움), 영상은 트림/루프
- **굵은 한글 자막**(Noto Sans CJK KR)을 외곽선·그림자와 함께 구워 넣음(ASS)
- ffmpeg 는 `imageio-ffmpeg` 정적 바이너리 사용 → 시스템 설치 불필요
- 이미지 슬로우 줌(Ken Burns)은 `zoompan` 이 매우 느려 **기본 OFF**(옵션)

## 자동화 경계(솔직하게)

- **렌더는 완전 무인**입니다(캡컷 불필요). 주제→대본→TTS→렌더까지 사람 손 0.
- **틱톡 게시**: 틱톡 정책상 **게시 직전 동의 1회**(AIGC/공개범위/미리보기 확인)가
  필수라, 완전 무인 게시는 불가하고 "확인 게이트"가 한 번 있습니다. 그 외 업로드
  준비(mp4→higgsfield 업로드→세션 생성)는 자동입니다.
- **AIGC 고지**: TTS/AI 요소가 있으면 틱톡에 `is_aigc=true` 로 정직하게 고지하세요.

## 업로드 연결(⑥)

- **틱톡(우선)**: `render` 로 만든 mp4 → higgsfield `media_upload` → `tiktok_prepare_publish`
  → `tiktok_publish`. 계정은 `tiktok_accounts`/`tiktok_connect` 로 연결.
- **유튜브(나중)**: YouTube Data API v3(OAuth). `publish.youtube_upload()` 에 자격증명 연결.
  **자격증명은 절대 커밋 금지, 환경변수/시크릿으로만** 주입.

## 다음 단계 제안 (우선순위)

1. **③ TTS 실연결** — higgsfield `generate_audio`(한국어 보이스)로 대본→나레이션 자동.
   `voice.py` 의 provider 자리에 REST 래퍼(독립 실행용)를 꽂거나, 세션에선 MCP 로 생성.
2. **⑥ 틱톡 게시 배선** — mp4 업로드 → prepare → publish 를 한 커맨드로(`shorts publish`).
3. **대본 생성 보조** — 주제 → 훅/본문/CTA 초안 자동 생성(페르소나·톤 반영), 사람 감수.
4. **성과 루프** — apify 로 잘 되는 훅·주제 지표 수집 → 다음 캘린더 보정.
5. **유튜브 업로드** — 자격증명 연결 후 매니페스트 기반 게시.

## 노션 브랜딩 반영

노션 브랜딩 문서(채널명·톤·타깃·CTA·비주얼 가이드)가 확정되면 `channel.yaml` 한 파일에
채워 넣으면 됩니다 → 모든 대본·자막·게시 메타에 일관 반영. (`examples/channel.example.yaml` 참고)
