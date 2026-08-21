"""로컬 웹 UI (FastAPI) — 키워드 입력 → 상위 글 / 쿠팡 매칭 / 한국어 초안.

    python -m threadscout.web        →  http://127.0.0.1:8010

엔드포인트
    GET  /                 화면
    GET  /api/health       토큰 설정 상태
    POST /api/scan         파이프라인 실행 → 결과 JSON
    POST /api/coupang      검색어 쿠팡 판매 여부 확인
    POST /api/report       마지막 결과를 HTML 리포트로 저장
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = Path(os.environ.get("THREADSCOUT_OUT", "output"))

# 동시에 여러 스캔이 돌면 Apify 비용만 나가므로 한 번에 하나만.
_SCAN_LOCK = asyncio.Lock()
_LAST_RESULT: Dict[str, Any] = {}


try:  # pydantic 은 fastapi 설치 시 함께 들어옴
    from pydantic import BaseModel
except ImportError:  # 웹 의존성 없이 임포트될 때
    BaseModel = object  # type: ignore[assignment,misc]


class ScanRequest(BaseModel):  # type: ignore[misc]
    keywords: List[str] = []
    from_json: Optional[str] = None
    max_posts: int = 50
    sort: str = "top"
    days: Optional[int] = 30
    top: int = 20
    min_views: int = 0
    min_likes: int = 0
    min_replies: int = 0
    max_followers: Optional[int] = None
    include_korean: bool = False
    languages: List[str] = []
    w_exposure: float = 0.25
    w_share: float = 0.25
    w_reply: float = 0.25
    w_reach: float = 0.15
    w_velocity: float = 0.10
    coupang: str = "auto"
    sub_id: str = "threads"
    max_matches: int = 10
    drafts: int = 5
    translate: bool = True
    apify_token: Optional[str] = None


class CoupangRequest(BaseModel):  # type: ignore[misc]
    keywords: List[str]
    limit: int = 5
    sub_id: str = "threads"
    apify_token: Optional[str] = None


def create_app():  # noqa: C901 — 라우트 정의라 길이만 김
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, JSONResponse
    from .collect import CollectError
    from .coupang import CoupangError, PartnersClient, pick_best, search_via_apify
    from .pipeline import PipelineOptions, run_pipeline
    from .benchmark import write_xlsx
    from .report import write_csv, write_html, write_json, write_markdown
    from .score import Filters, ScoreWeights

    app = FastAPI(title="threadscout", docs_url=None, redoc_url=None)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        return {
            "apify_token": bool(os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN")),
            "coupang_partners": PartnersClient.from_env() is not None,
            "translator": _has_translator(),
        }

    @app.post("/api/scan")
    async def scan(req: ScanRequest) -> JSONResponse:
        if not req.keywords and not req.from_json:
            raise HTTPException(status_code=400, detail="키워드를 하나 이상 입력하세요.")
        if _SCAN_LOCK.locked():
            raise HTTPException(status_code=409, detail="이미 수집이 진행 중입니다. 끝난 뒤 다시 시도하세요.")

        options = PipelineOptions(
            keywords=tuple(k.strip() for k in req.keywords if k.strip()),
            from_json=req.from_json or None,
            max_posts=req.max_posts,
            sort=req.sort,
            days=req.days,
            apify_token=req.apify_token or None,
            filters=Filters(
                exclude_korean=not req.include_korean,
                languages=tuple(req.languages),
                min_views=req.min_views,
                min_likes=req.min_likes,
                min_replies=req.min_replies,
                max_age_days=req.days,
                max_followers=req.max_followers,
            ),
            weights=ScoreWeights(
                exposure=req.w_exposure, share_rate=req.w_share, reply_rate=req.w_reply,
                reach=req.w_reach, velocity=req.w_velocity,
            ),
            top=req.top,
            coupang=req.coupang,
            coupang_sub_id=req.sub_id,
            max_matches=req.max_matches,
            draft_limit=req.drafts,
            translate=req.translate,
        )

        logs: List[str] = []
        async with _SCAN_LOCK:
            try:
                result = await asyncio.to_thread(run_pipeline, options, log=logs.append)
            except (CollectError, CoupangError, RuntimeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        result["logs"] = logs
        _LAST_RESULT.clear()
        _LAST_RESULT.update(result)
        return JSONResponse(result)

    @app.post("/api/coupang")
    async def coupang(req: CoupangRequest) -> Dict[str, Any]:
        client = PartnersClient.from_env(sub_id=req.sub_id)
        out: List[Dict[str, Any]] = []
        try:
            if client is not None:
                for keyword in req.keywords:
                    best = pick_best(keyword, await asyncio.to_thread(client.search, keyword, req.limit))
                    out.append({"keyword": keyword, "found": best is not None,
                                "product": best.to_dict() if best else None})
            else:
                from .collect import get_token

                token = get_token(req.apify_token)
                grouped = await asyncio.to_thread(
                    search_via_apify, req.keywords, token=token, max_per_keyword=req.limit
                )
                for keyword in req.keywords:
                    best = pick_best(keyword, grouped.get(keyword, []))
                    out.append({"keyword": keyword, "found": best is not None,
                                "product": best.to_dict() if best else None})
        except (CollectError, CoupangError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"results": out, "affiliate": client is not None}

    @app.post("/api/report")
    async def report() -> Dict[str, Any]:
        if not _LAST_RESULT:
            raise HTTPException(status_code=400, detail="먼저 분석을 실행하세요.")
        stem = f"threadscout_{time.strftime('%Y%m%d_%H%M%S')}"
        base = OUTPUT_DIR / stem
        paths = [
            write_html(_LAST_RESULT, base.with_suffix(".html")),
            write_markdown(_LAST_RESULT, base.with_suffix(".md")),
            write_csv(_LAST_RESULT, base.with_suffix(".csv")),
            write_json(_LAST_RESULT, base.with_suffix(".json")),
        ]
        try:
            paths.append(write_xlsx(_LAST_RESULT, base.with_suffix(".xlsx")))
        except RuntimeError:  # openpyxl 미설치 — 나머지 포맷만 저장
            pass
        return {"saved": [str(p) for p in paths]}

    return app


def _has_translator() -> bool:
    try:
        import deep_translator  # noqa: F401,WPS433
    except ImportError:
        return False
    return True
