"""캡컷 초안 폴더 경로 생성 테스트 (파일시스템 비의존)."""

import os

from capcut_agent.capcut_paths import candidate_draft_folders


def test_macos_candidates():
    paths = candidate_draft_folders(platform="darwin", home="/Users/me")
    assert any(p.startswith("/Users/me/Movies/CapCut") for p in paths)
    assert any("JianyingPro" in p for p in paths)
    assert all(p.endswith(os.path.join("User Data", "Projects", "com.lveditor.draft")) for p in paths)


def test_windows_candidates(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    paths = candidate_draft_folders(platform="win32", home=r"C:\Users\me")
    assert any("CapCut" in p and "com.lveditor.draft" in p for p in paths)


def test_linux_candidates():
    paths = candidate_draft_folders(platform="linux", home="/home/me")
    assert len(paths) >= 1
    assert all("com.lveditor.draft" in p for p in paths)
