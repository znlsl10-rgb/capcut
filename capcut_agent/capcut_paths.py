"""캡컷/剪映 초안 폴더 자동 감지.

OS별로 캡컷(및 중국판 剪映)이 초안을 저장하는 표준 위치를 확인해
존재하는 폴더 목록을 돌려줍니다. 사용자가 `--draft-folder` 를 생략하면
CLI 가 이 결과로 자동 지정합니다.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

# 초안 폴더의 마지막 경로 조각 (모든 OS 공통)
_DRAFT_TAIL = os.path.join("User Data", "Projects", "com.lveditor.draft")

# 앱 폴더명 후보 (CapCut 글로벌 / 중국판 剪映)
_APP_DIRS = ("CapCut", "JianyingPro")


def candidate_draft_folders(platform: Optional[str] = None,
                            home: Optional[str] = None) -> List[str]:
    """OS 표준 위치의 초안 폴더 후보 경로를 만듭니다(존재 여부는 확인 안 함).

    Args:
        platform: sys.platform 오버라이드(테스트용).
        home: 홈 디렉터리 오버라이드(테스트용).
    """
    platform = platform or sys.platform
    home = home or os.path.expanduser("~")
    roots: List[str] = []

    if platform == "darwin":  # macOS
        base = os.path.join(home, "Movies")
        roots = [os.path.join(base, app) for app in _APP_DIRS]
    elif platform.startswith("win"):  # Windows
        local = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        roots = [os.path.join(local, app) for app in _APP_DIRS]
    else:  # Linux 등 — 공식 지원 아님, 홈 아래 관례적 경로만 시도
        roots = [os.path.join(home, app) for app in _APP_DIRS]

    return [os.path.join(root, _DRAFT_TAIL) for root in roots]


def find_draft_folders(platform: Optional[str] = None,
                       home: Optional[str] = None) -> List[str]:
    """실제로 존재하는 초안 폴더만 돌려줍니다."""
    return [p for p in candidate_draft_folders(platform, home) if os.path.isdir(p)]


def default_draft_folder(platform: Optional[str] = None,
                         home: Optional[str] = None) -> Optional[str]:
    """자동 감지된 첫 번째 초안 폴더. 없으면 None."""
    found = find_draft_folders(platform, home)
    return found[0] if found else None
