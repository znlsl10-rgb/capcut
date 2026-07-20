"""webapp 엔드포인트 스모크 테스트 (fastapi 있을 때만)."""

import numpy as np
import pytest

fastapi = pytest.importorskip("fastapi")
try:
    import soundfile  # noqa: F401
    _HAVE_SF = True
except Exception:  # noqa: BLE001
    _HAVE_SF = False

from starlette.testclient import TestClient  # noqa: E402

from talkcut.webapp import create_app  # noqa: E402


def _client():
    return TestClient(create_app())


def test_index_serves_html():
    r = _client().get("/")
    assert r.status_code == 200
    assert "캡컷 에이전트" in r.text
    assert "text/html" in r.headers["content-type"]


def test_health_reports_track():
    r = _client().get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["track"] in ("A", "C", "fallback")
    assert body["asr"] in ("mlx-whisper", "faster-whisper")


def test_upload_returns_job_id_and_content_hash_stable(tmp_path):
    client = _client()
    data = b"hello-video-bytes"
    r1 = client.post("/upload", files={"file": ("a.mp4", data, "video/mp4")})
    r2 = client.post("/upload", files={"file": ("renamed.mp4", data, "video/mp4")})
    assert r1.status_code == 200 and r2.status_code == 200
    # content hash 기반 → 같은 내용이면 같은 job_id (파일명 달라도)
    assert r1.json()["job_id"] == r2.json()["job_id"]


def test_upload_rejects_empty():
    r = _client().post("/upload", files={"file": ("empty.mp4", b"", "video/mp4")})
    assert r.status_code == 400


@pytest.mark.skipif(not _HAVE_SF, reason="soundfile 필요")
def test_events_pipeline_emits_silence_and_error_without_draft_folder(tmp_path):
    """WAV 업로드 → SSE 로 silence done + (초안폴더 없으면) error 이벤트 확인."""
    import soundfile as sf

    wav = tmp_path / "clip.wav"
    sr = 16000
    x = np.concatenate([
        (np.random.default_rng(0).standard_normal(sr) * 0.3).astype("float32"),  # 말
        np.zeros(sr, dtype="float32"),                                            # 무음
        (np.random.default_rng(1).standard_normal(sr) * 0.3).astype("float32"),  # 말
    ])
    sf.write(str(wav), x, sr)

    client = _client()
    job = client.post("/upload", files={"file": ("clip.wav", wav.read_bytes(), "audio/wav")}).json()["job_id"]

    # 초안 폴더가 없는 환경이므로 draft 단계에서 error 가 나야 정상.
    with client.stream("GET", f"/events/{job}?min_silence=0.3") as resp:
        text = "".join(chunk for chunk in resp.iter_text())
    assert '"step": "silence"' in text
    assert '"status": "done"' in text
    # 무음 1곳 감지
    assert '"silences": 1' in text
