"""수집 — Apify 액터 실행 / 로컬 JSON 로드.

Threads 공개 API 는 검색을 열어주지 않아서, 실무에서는 Apify 의 Threads 액터를 씁니다.
기본값은 조회수·공유수까지 주는 futurizerush/meta-threads-scraper.

    export APIFY_TOKEN=apify_api_...
    python -m threadscout scan --keyword "air fryer" --keyword "amazon finds"

비용을 아끼려면 한 번 수집한 원시 데이터를 --save-raw 로 저장해두고
--from-json 으로 몇 번이든 다시 분석하세요(재분석은 무료).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

API_BASE = "https://api.apify.com/v2"

# 기본 액터: 조회수(view_count)·공유수(share_count)·팔로워까지 제공.
THREADS_ACTOR = "futurizerush/meta-threads-scraper"
# 대안(조회수 미제공 → 좋아요 기반 추정으로 동작): "igview-owner/threads-search-scraper"


class CollectError(RuntimeError):
    pass


def _actor_path(actor: str) -> str:
    return actor.replace("/", "~")


def _api_call(url: str, *, method: str = "GET", body: Optional[dict] = None, timeout: int = 60) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise CollectError(f"Apify API 오류 {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise CollectError(f"Apify 연결 실패: {exc.reason}") from exc
    return json.loads(raw) if raw else None


def get_token(explicit: Optional[str] = None) -> str:
    token = (explicit or os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN") or "").strip()
    if not token:
        raise CollectError(
            "APIFY_TOKEN 이 없습니다.\n"
            "  1) https://console.apify.com/settings/integrations 에서 토큰 발급\n"
            "  2) export APIFY_TOKEN=apify_api_...\n"
            "토큰 없이 분석만 하려면 --from-json <저장된 원시 JSON> 을 쓰세요."
        )
    return token


def run_actor(
    actor: str,
    run_input: Dict[str, Any],
    *,
    token: str,
    wait_seconds: int = 600,
    poll_seconds: float = 5.0,
    memory_mbytes: int = 1024,
    log: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """액터를 실행하고 결과 데이터셋 아이템을 전부 가져온다."""
    def _log(msg: str) -> None:
        if log:
            log(msg)

    start_url = (
        f"{API_BASE}/acts/{_actor_path(actor)}/runs"
        f"?token={urllib.parse.quote(token)}&memory={memory_mbytes}"
    )
    started = _api_call(start_url, method="POST", body=run_input)
    run = (started or {}).get("data") or {}
    run_id, dataset_id = run.get("id"), run.get("defaultDatasetId")
    if not run_id:
        raise CollectError(f"액터 실행 실패: {started}")
    _log(f"[apify] {actor} 실행 시작 (run={run_id})")

    deadline = time.monotonic() + wait_seconds
    status = run.get("status", "RUNNING")
    while status in ("READY", "RUNNING") and time.monotonic() < deadline:
        time.sleep(poll_seconds)
        info = _api_call(f"{API_BASE}/actor-runs/{run_id}?token={urllib.parse.quote(token)}")
        run = (info or {}).get("data") or {}
        status = run.get("status", status)
        dataset_id = run.get("defaultDatasetId", dataset_id)
        _log(f"[apify] 상태={status}")

    if status in ("READY", "RUNNING"):
        _log(f"[apify] 대기 시간 초과 — 지금까지 모인 결과만 사용합니다 (run={run_id})")
    elif status != "SUCCEEDED":
        _log(f"[apify] 실행 종료 상태={status} — 부분 결과가 있으면 그대로 사용합니다")

    if not dataset_id:
        raise CollectError("결과 데이터셋이 없습니다.")
    return fetch_dataset(dataset_id, token=token)


def fetch_dataset(dataset_id: str, *, token: str, page_size: int = 1000) -> List[Dict[str, Any]]:
    """데이터셋 아이템 페이지네이션 수집."""
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        url = (
            f"{API_BASE}/datasets/{dataset_id}/items"
            f"?token={urllib.parse.quote(token)}&clean=true&format=json"
            f"&offset={offset}&limit={page_size}"
        )
        page = _api_call(url) or []
        if not isinstance(page, list) or not page:
            break
        out.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return out


def collect_threads(
    keywords: Sequence[str],
    *,
    token: str,
    max_posts: int = 50,
    sort: str = "top",
    days: Optional[int] = None,
    actor: str = THREADS_ACTOR,
    log: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """키워드로 Threads 공개 게시물 수집 (액터별 입력 형식 자동 구성)."""
    if not keywords:
        raise CollectError("검색 키워드가 필요합니다.")

    if actor == THREADS_ACTOR:
        run_input: Dict[str, Any] = {
            "mode": "search",
            "keywords": list(keywords),
            "max_posts": max_posts,
            "search_filter": sort,
        }
        if days:
            run_input["start_date"] = f"{days} days"
    elif "threads-search-scraper" in actor:
        # 이 계열은 검색어 1개씩 → 키워드마다 따로 돌린다.
        items: List[Dict[str, Any]] = []
        for kw in keywords:
            part = run_actor(
                actor,
                {"searchQuery": kw, "sort": sort, "maxPosts": max_posts},
                token=token,
                log=log,
            )
            for row in part:
                row.setdefault("search_keyword", kw)
            items.extend(part)
        return items
    else:
        run_input = {"mode": "search", "searchQueries": list(keywords), "maxPosts": max_posts}

    return run_actor(actor, run_input, token=token, log=log)


def load_json(path: str | Path) -> List[Dict[str, Any]]:
    """저장해둔 원시 JSON(list 또는 {"items": [...]}) 로드."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("items", "data", "results", "posts"):
            if isinstance(data.get(key), list):
                return data[key]
        raise CollectError(f"JSON 안에서 목록을 찾지 못했습니다: {path}")
    if not isinstance(data, list):
        raise CollectError(f"지원하지 않는 JSON 형식: {path}")
    return data


def save_raw(items: Iterable[Dict[str, Any]], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(list(items), ensure_ascii=False, indent=2), encoding="utf-8")
    return out
