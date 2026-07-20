"""로컬 웹앱 (FastAPI): drag/drop 업로드 → SSE 스테퍼 → 점프컷 드래프트.

런타임 단계(SSE 이벤트): upload → silence → asr → filler → draft → done
  - 현재(2단)는 silence·draft 만 실제 실행. asr·filler 는 3·4단 자리(skipped).
  - ASR 은 asyncio.Lock 으로 직렬화(numba 비안전 → 동시 호출 시 segfault 방지).
  - 단계당 최소 0.5s 강제 지연(캐시 hit 시 애니메이션 가시화).
  - ASR/무음 캐시는 content hash 기반(mtime 아님 → 매 업로드 miss 방지).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

# 무거운 의존성은 함수 내부에서 지연 임포트.

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = Path(tempfile.gettempdir()) / "talkcut_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MIN_STEP_SECONDS = 0.5  # 단계당 최소 지연

# ASR 직렬화용 전역 Lock (numba 비안전). 3단부터 실제 사용.
_ASR_LOCK = asyncio.Lock()

# content hash → 결과 캐시
_silence_cache: Dict[str, Any] = {}
# job_id(=hash) → 업로드 파일 경로
_jobs: Dict[str, str] = {}


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


async def _min_delay(started: float) -> None:
    elapsed = time.monotonic() - started
    if elapsed < MIN_STEP_SECONDS:
        await asyncio.sleep(MIN_STEP_SECONDS - elapsed)


def _sse(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _resolve_draft_folder(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    try:
        from capcut_agent.capcut_paths import default_draft_folder

        return default_draft_folder()
    except Exception:  # noqa: BLE001
        return None


async def _run_pipeline(job_id: str, params: Dict[str, Any]):
    """업로드된 영상 1개를 처리하며 SSE 이벤트를 순차 방출."""
    from .audio_silence import analyze_silence
    from .jumpcut import build_jumpcut_draft

    path = _jobs.get(job_id)
    if not path or not os.path.isfile(path):
        yield _sse({"step": "error", "message": "업로드 파일을 찾을 수 없습니다. 다시 올려주세요."})
        return

    yield _sse({"step": "upload", "status": "done", "info": os.path.basename(path)})

    # --- 무음 감지 -------------------------------------------------------
    yield _sse({"step": "silence", "status": "running"})
    t0 = time.monotonic()
    try:
        cached = _silence_cache.get(job_id)
        if cached is None:
            cached = await asyncio.to_thread(
                analyze_silence,
                path,
                threshold_db=float(params.get("threshold_db", -35.0)),
                min_silence=float(params.get("min_silence", 0.35)),
                pad=float(params.get("pad", 0.06)),
                min_keep=float(params.get("min_keep", 0.20)),
            )
            _silence_cache[job_id] = cached
        await _min_delay(t0)
    except Exception as exc:  # noqa: BLE001
        yield _sse({"step": "error", "message": f"무음 분석 실패: {exc} (ffmpeg 설치 확인)"})
        return
    yield _sse({
        "step": "silence", "status": "done",
        "info": {
            "duration": cached.duration,
            "silences": len(cached.silences),
            "keeps": len(cached.keeps),
            "removed": round(cached.removed, 2),
            "removed_pct": round(cached.removed / cached.duration * 100, 1) if cached.duration else 0,
        },
    })

    # --- ASR (3단 예정) / 잔말·NG (4단 예정) -----------------------------
    yield _sse({"step": "asr", "status": "skipped", "info": "3단에서 구현 (Transcript)"})
    yield _sse({"step": "filler", "status": "skipped", "info": "4단에서 구현 (잔말/NG)"})

    # --- 드래프트 생성 ---------------------------------------------------
    draft_folder = _resolve_draft_folder(params.get("draft_folder"))
    if not draft_folder or not os.path.isdir(draft_folder):
        yield _sse({
            "step": "error",
            "message": "캡컷 초안 폴더를 찾지 못했습니다. 캡컷을 1회 실행하거나 서버에 --draft-folder 로 지정하세요.",
        })
        return

    yield _sse({"step": "draft", "status": "running"})
    t0 = time.monotonic()
    name = params.get("name") or (Path(path).stem + "_jumpcut")
    try:
        res = await asyncio.to_thread(
            build_jumpcut_draft, path, cached.keeps, draft_folder, name,
            fps=int(params.get("fps", 30)),
        )
        await _min_delay(t0)
    except Exception as exc:  # noqa: BLE001
        yield _sse({"step": "error", "message": f"드래프트 생성 실패: {exc}"})
        return
    yield _sse({"step": "draft", "status": "done", "info": {"segments": res.n_segments}})

    yield _sse({
        "step": "done", "status": "done",
        "result": {
            "draft_name": name,
            "draft_path": res.draft_path,
            "segments": res.n_segments,
            "kept": res.kept_duration,
            "removed": round(cached.removed, 2),
            "duration": cached.duration,
            "warnings": res.warnings,
        },
    })


def create_app(*, draft_folder: Optional[str] = None):
    """FastAPI 앱 생성. draft_folder 를 주면 자동감지 대신 그 경로 사용.

    라우트는 Starlette 레벨(add_route)로 등록합니다. FastAPI 의 파라미터 해석
    (pydantic)을 우회해 fastapi/starlette 버전 조합에 견고하도록 하기 위함입니다.
    """
    from fastapi import FastAPI
    from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

    app = FastAPI(title="캡컷 에이전트")
    app.state.draft_folder = draft_folder

    async def index(request):  # noqa: WPS430
        return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    async def upload(request):  # noqa: WPS430
        form = await request.form()
        up = form.get("file")
        if up is None or not hasattr(up, "read"):
            return JSONResponse({"error": "파일이 없습니다."}, status_code=400)
        data = await up.read()
        if not data:
            return JSONResponse({"error": "빈 파일입니다."}, status_code=400)
        job_id = _hash_bytes(data)
        ext = os.path.splitext(getattr(up, "filename", "") or "")[1] or ".mp4"
        dest = UPLOAD_DIR / f"{job_id}{ext}"
        if not dest.exists():  # content hash → 동일 파일 재업로드 시 재사용
            dest.write_bytes(data)
        _jobs[job_id] = str(dest)
        _silence_cache.pop(job_id, None)  # 파라미터 바뀔 수 있으니 재계산 대비
        return JSONResponse({"job_id": job_id, "filename": getattr(up, "filename", None)})

    async def events(request):  # noqa: WPS430
        job_id = request.path_params["job_id"]
        params: Dict[str, Any] = dict(request.query_params)
        if app.state.draft_folder and "draft_folder" not in params:
            params["draft_folder"] = app.state.draft_folder

        async def gen():
            async for chunk in _run_pipeline(job_id, params):
                if await request.is_disconnected():
                    break
                yield chunk

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def health(request):  # noqa: WPS430
        from .osdetect import check_environment

        env = check_environment(check_draft_folder=True)
        return JSONResponse({
            "track": env.track, "asr": env.asr_backend,
            "draft_folder": app.state.draft_folder or env.draft_folder,
            "missing": env.missing_tools,
        })

    app.add_route("/", index, methods=["GET"])
    app.add_route("/upload", upload, methods=["POST"])
    app.add_route("/events/{job_id}", events, methods=["GET"])
    app.add_route("/health", health, methods=["GET"])
    return app
