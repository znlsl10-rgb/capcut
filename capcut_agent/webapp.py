"""뮤직비디오 로컬 웹앱 (FastAPI): 곡 선택 → 배경 자동 → 비트 컷 + 영한 이중 자막.

SSE 런타임 단계: upload → beat → lyrics(EN 교정 + KR) → background(자동) → draft → done
  - ASR(Whisper)은 asyncio.Lock 으로 직렬화(numba 비안전).
  - 단계당 최소 0.5s 지연(캐시 hit 시 애니 가시화).
  - 곡 오디오/무거운 처리는 to_thread 로 이벤트 루프 비블로킹.

서버는 --songbook 으로 곡별 정답 가사/무드를 로드합니다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = Path(tempfile.gettempdir()) / "capcut_mv_uploads"
BG_CACHE = Path(tempfile.gettempdir()) / "capcut_mv_backgrounds"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
BG_CACHE.mkdir(parents=True, exist_ok=True)

MIN_STEP_SECONDS = 0.5
_ASR_LOCK = asyncio.Lock()  # Whisper 직렬화
_jobs: Dict[str, str] = {}          # job_id → 오디오 경로
_cache: Dict[str, Any] = {}         # (job_id|song|params) → 결과


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _sse(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def _min_delay(started: float) -> None:
    elapsed = time.monotonic() - started
    if elapsed < MIN_STEP_SECONDS:
        await asyncio.sleep(MIN_STEP_SECONDS - elapsed)


def _resolve_draft_folder(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    try:
        from .capcut_paths import default_draft_folder

        return default_draft_folder()
    except Exception:  # noqa: BLE001
        return None


async def _pipeline(app, job_id: str, params: Dict[str, Any]):
    """곡 1개 → 뮤직비디오 드래프트. SSE 이벤트를 순차 방출."""
    from .audio import analyze_audio
    from .backgrounds import auto_background_clips
    from .config import AgentConfig
    from .draft_builder import build_draft
    from .lyrics import clamp_segments_to_duration
    from .songbook import find_song
    from .translate import build_secondary

    audio_path = _jobs.get(job_id)
    if not audio_path or not os.path.isfile(audio_path):
        yield _sse({"step": "error", "message": "업로드된 오디오를 찾을 수 없습니다. 다시 올려주세요."})
        return
    yield _sse({"step": "upload", "status": "done", "info": os.path.basename(audio_path)})

    songs = app.state.songs
    song = find_song(songs, params.get("song", "")) if songs else None
    if song is None:
        yield _sse({"step": "error", "message": "곡을 찾지 못했습니다. 목록에서 곡을 선택하세요."})
        return

    # --- 비트 분석 -------------------------------------------------------
    yield _sse({"step": "beat", "status": "running"})
    t0 = time.monotonic()
    try:
        beatmap = await asyncio.to_thread(analyze_audio, audio_path)
        await _min_delay(t0)
    except Exception as exc:  # noqa: BLE001
        yield _sse({"step": "error", "message": f"비트 분석 실패: {exc} (ffmpeg 설치 확인)"})
        return
    yield _sse({"step": "beat", "status": "done",
                "info": {"duration": round(beatmap.duration, 1), "tempo": round(float(beatmap.tempo)),
                         "beats": len(beatmap.beats)}})

    # --- 가사(영어 교정 + 한글) -----------------------------------------
    yield _sse({"step": "lyrics", "status": "running"})
    t0 = time.monotonic()
    en_lines = song.lyric_lines()
    try:
        segments = await _build_lyrics(audio_path, en_lines, beatmap.duration, params)
        segments = clamp_segments_to_duration(segments, beatmap.duration)
    except Exception as exc:  # noqa: BLE001
        yield _sse({"step": "error", "message": f"가사 처리 실패: {exc}"})
        return
    # 한글 이중 자막(실패해도 영어 단일로 진행 — 비치명적)
    ko_mode = params.get("ko", "auto")
    ko_note = ""
    if ko_mode != "off":
        try:
            segments = await asyncio.to_thread(
                build_secondary, segments, auto_translate=(ko_mode == "auto"), target="ko",
            )
        except Exception as exc:  # noqa: BLE001
            ko_note = f" (한글 자동번역 건너뜀: deep-translator 미설치/네트워크)"
    await _min_delay(t0)
    n_ko = sum(1 for s in segments if s.secondary)
    yield _sse({"step": "lyrics", "status": "done",
                "info": {"lines": len(segments), "ko": n_ko, "mood": song.mood,
                         "style": song.style(), "note": ko_note}})

    # --- 배경 자동 -------------------------------------------------------
    yield _sse({"step": "background", "status": "running"})
    t0 = time.monotonic()
    bg = await asyncio.to_thread(auto_background_clips, song.mood, str(BG_CACHE / song.mood))
    await _min_delay(t0)
    guide = song.background_guide()
    yield _sse({"step": "background", "status": "done",
                "info": {"clips": len(bg), "guide": f"{guide.get('video','')} · {guide.get('color','')}"}})

    # --- 드래프트 --------------------------------------------------------
    draft_folder = _resolve_draft_folder(params.get("draft_folder") or app.state.draft_folder)
    if not draft_folder or not os.path.isdir(draft_folder):
        yield _sse({"step": "error", "message": "캡컷 초안 폴더를 찾지 못했습니다. 캡컷 1회 실행 또는 서버에 --draft-folder 지정."})
        return

    yield _sse({"step": "draft", "status": "running"})
    t0 = time.monotonic()
    name = _safe_name(song.title)
    cfg = AgentConfig(
        audio_path=audio_path, draft_folder=draft_folder,
        background_paths=list(bg), clip_order="sequential",
        draft_name=name, style=song.style(), emphasize_lyrics=True,
    )
    try:
        res_path, warnings = await asyncio.to_thread(build_draft, cfg, beatmap, segments)
        await _min_delay(t0)
    except Exception as exc:  # noqa: BLE001
        yield _sse({"step": "error", "message": f"드래프트 생성 실패: {exc}"})
        return
    yield _sse({"step": "draft", "status": "done", "info": {"warnings": len(warnings)}})

    yield _sse({"step": "done", "status": "done", "result": {
        "song": song.title, "mood": song.mood, "style": song.style(),
        "draft_name": name, "draft_path": res_path,
        "duration": round(beatmap.duration, 1), "tempo": round(float(beatmap.tempo)),
        "lines": len(segments), "ko": n_ko, "clips": len(bg),
    }})


async def _build_lyrics(audio_path, en_lines, duration, params):
    """EN 가사에 타이밍 부여: Whisper 교정(가능 시) → 실패/부재 시 분배."""
    from .lyrics import align_lyrics, correct_lyrics

    if params.get("timing", "whisper") == "whisper":
        try:
            async with _ASR_LOCK:  # numba 직렬화
                return await asyncio.to_thread(
                    correct_lyrics, audio_path, en_lines,
                    model_size=params.get("whisper_model", "small"), duration=duration,
                )
        except Exception:  # noqa: BLE001 — whisper 없거나 실패 → 분배 폴백
            pass
    return align_lyrics(en_lines, whisper_segments=None, duration=duration)


def _safe_name(title: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip()
    return (keep or "music_video").replace(" ", "_") + "_mv"


def create_app(*, songbook: Optional[str] = None, draft_folder: Optional[str] = None):
    """뮤직비디오 웹앱 생성.

    songbook 경로를 주면 곡별 가사/무드를 로드합니다. 라우트는 Starlette
    레벨(add_route)로 등록해 fastapi/starlette 버전 조합에 견고합니다.
    """
    from fastapi import FastAPI
    from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

    app = FastAPI(title="캡컷 에이전트 · 뮤직비디오")
    app.state.draft_folder = draft_folder
    app.state.songbook_path = songbook
    app.state.songs = {}
    if songbook and os.path.isfile(songbook):
        try:
            from .songbook import load_songbook

            app.state.songs = load_songbook(songbook)
        except Exception:  # noqa: BLE001
            app.state.songs = {}

    async def index(request):  # noqa: WPS430
        return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    async def songs(request):  # noqa: WPS430
        out = [
            {"title": s.title, "mood": s.mood, "style": s.style(),
             "duration": s.duration, "lines": len(s.lyric_lines())}
            for s in app.state.songs.values()
        ]
        out.sort(key=lambda x: (x["mood"], x["title"]))
        return JSONResponse({"songbook": app.state.songbook_path, "count": len(out), "songs": out})

    async def upload(request):  # noqa: WPS430
        form = await request.form()
        up = form.get("file")
        if up is None or not hasattr(up, "read"):
            return JSONResponse({"error": "파일이 없습니다."}, status_code=400)
        data = await up.read()
        if not data:
            return JSONResponse({"error": "빈 파일입니다."}, status_code=400)
        job_id = _hash_bytes(data)
        ext = os.path.splitext(getattr(up, "filename", "") or "")[1] or ".mp3"
        dest = UPLOAD_DIR / f"{job_id}{ext}"
        if not dest.exists():
            dest.write_bytes(data)
        _jobs[job_id] = str(dest)
        return JSONResponse({"job_id": job_id, "filename": getattr(up, "filename", None)})

    async def events(request):  # noqa: WPS430
        job_id = request.path_params["job_id"]
        params: Dict[str, Any] = dict(request.query_params)

        async def gen():
            async for chunk in _pipeline(app, job_id, params):
                if await request.is_disconnected():
                    break
                yield chunk

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    app.add_route("/", index, methods=["GET"])
    app.add_route("/songs", songs, methods=["GET"])
    app.add_route("/upload", upload, methods=["POST"])
    app.add_route("/events/{job_id}", events, methods=["GET"])
    return app
