"""threadscout 웹 엔드포인트 스모크 테스트 (fastapi 있을 때만)."""

import json
import time

import pytest

pytest.importorskip("fastapi")

from starlette.testclient import TestClient  # noqa: E402

from threadscout.webapp import _LAST_RESULT, create_app  # noqa: E402

NOW = time.time()


def _raw(i):
    return {
        "post_id": str(i),
        "post_url": f"https://www.threads.com/@u/post/{i}",
        "username": "u",
        "followers_count": 9000,
        "text_content": "I bought this air fryer for $99 and it is worth it. Best kitchen buy.",
        "created_at_timestamp": int(NOW - 3600 * (i + 1)),
        "view_count": 10000 * (i + 1),
        "like_count": 200 * (i + 1),
        "reply_count": 30 * (i + 1),
        "repost_count": 10 * (i + 1),
        "share_count": 5 * (i + 1),
        "language": "en",
    }


@pytest.fixture()
def client():
    _LAST_RESULT.clear()  # 모듈 전역 캐시 → 테스트 간 격리
    return TestClient(create_app())


def test_index_and_health(client):
    assert client.get("/").status_code == 200
    body = client.get("/api/health").json()
    assert set(body) == {"apify_token", "coupang_partners", "translator"}


def test_scan_requires_keywords(client):
    assert client.post("/api/scan", json={"keywords": []}).status_code == 400


def test_scan_from_json(tmp_path, client):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps([_raw(i) for i in range(5)]), encoding="utf-8")
    res = client.post("/api/scan", json={
        "keywords": [], "from_json": str(raw), "coupang": "off",
        "translate": False, "top": 5, "drafts": 2, "days": None,
    })
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["count"] == 5
    assert len(body["posts"]) == 5
    assert body["drafts"] and "쿠팡 파트너스" in body["drafts"][0]["text"]


def test_report_requires_prior_scan(client):
    assert client.post("/api/report").status_code == 400
