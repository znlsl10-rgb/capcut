"""유튜브/웹 링크 판별 순수 로직 테스트 (yt-dlp 불필요)."""

import pytest

from capcut_agent.fetch import (
    is_url,
    is_youtube,
    resolve_reference,
    youtube_id,
)


def test_is_url():
    assert is_url("https://youtube.com/watch?v=abc")
    assert is_url("http://example.com/v.mp4")
    assert not is_url("ref.mp4")
    assert not is_url("/home/user/ref.mp4")


def test_is_youtube():
    assert is_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_youtube("https://youtu.be/dQw4w9WgXcQ")
    assert not is_youtube("https://vimeo.com/123")


def test_youtube_id_watch():
    assert youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_youtube_id_short_and_shorts():
    assert youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_youtube_id_none():
    assert youtube_id("https://example.com/nope") == ""


def test_resolve_reference_local_file(tmp_path):
    f = tmp_path / "ref.mp4"
    f.write_bytes(b"x")
    assert resolve_reference(str(f)) == str(f)


def test_resolve_reference_missing_local():
    with pytest.raises(FileNotFoundError):
        resolve_reference("/no/such/file.mp4")
