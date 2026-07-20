"""뮤직비디오 webapp + 배경 자동 생성 테스트."""

import os

import pytest

pytest.importorskip("fastapi")
from starlette.testclient import TestClient  # noqa: E402

from capcut_agent.backgrounds import _variants, auto_background_clips  # noqa: E402
from capcut_agent.webapp import create_app  # noqa: E402


# --- 배경 자동 생성 ------------------------------------------------------
def test_variants_count_and_range():
    v = _variants((18, 48, 110), 6)
    assert len(v) == 6
    for top, bot in v:
        for ch in (*top, *bot):
            assert 0 <= ch <= 255


def test_auto_background_generates_pngs(tmp_path):
    paths = auto_background_clips("각성", str(tmp_path), count=4, width=64, height=100)
    assert len(paths) == 4
    for p in paths:
        assert os.path.isfile(p) and p.endswith(".png") and os.path.getsize(p) > 0


def test_auto_background_prefers_library(tmp_path):
    lib = tmp_path / "backgrounds" / "각성"
    lib.mkdir(parents=True)
    (lib / "clip.mp4").write_bytes(b"x")
    paths = auto_background_clips("각성", str(tmp_path / "out"),
                                  library_root=str(tmp_path / "backgrounds"))
    assert len(paths) == 1 and paths[0].endswith("clip.mp4")


# --- webapp --------------------------------------------------------------
def test_index_and_songs_empty_without_songbook():
    c = TestClient(create_app())
    assert c.get("/").status_code == 200
    body = c.get("/songs").json()
    assert body["count"] == 0 and body["songs"] == []


def test_songs_lists_from_songbook(tmp_path, monkeypatch):
    # 가짜 songbook: load_songbook 을 스텁
    import capcut_agent.webapp as wa
    from capcut_agent.songbook import Song

    def fake_load(path):
        return {"Born to Win": Song(title="Born to Win", mood="각성",
                                    raw_lyrics="[Intro]\nI was born to win\nnever look down")}

    monkeypatch.setattr("capcut_agent.songbook.load_songbook", fake_load)
    f = tmp_path / "sb.xlsx"
    f.write_bytes(b"x")
    c = TestClient(create_app(songbook=str(f)))
    body = c.get("/songs").json()
    assert body["count"] == 1
    assert body["songs"][0]["title"] == "Born to Win"
    assert body["songs"][0]["style"] == "goosebump"


def test_upload_returns_job_id():
    c = TestClient(create_app())
    r = c.post("/upload", files={"file": ("song.mp3", b"audio-bytes", "audio/mpeg")})
    assert r.status_code == 200 and "job_id" in r.json()
