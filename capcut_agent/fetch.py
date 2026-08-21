"""참고 영상 확보 — 유튜브/웹 링크 다운로드.

`--reference` 에 파일 경로 대신 **유튜브(또는 웹) 링크**를 넣으면, 이 모듈이
영상을 내려받아 로컬 파일로 만들고 그 경로를 돌려줍니다. 그 파일을 기존
`benchmark.analyze_reference()` 가 분석합니다.

다운로드는 표준 도구 **yt-dlp** 를 사용합니다(지연 실행). URL 판별 등 순수
로직은 의존성 없이 테스트 가능합니다.
"""

from __future__ import annotations

import os
import re


def is_url(text: str) -> bool:
    """http(s) 링크인지 판별 (순수 함수)."""
    return bool(re.match(r"^https?://", text.strip(), re.IGNORECASE))


def is_youtube(text: str) -> bool:
    """유튜브 링크인지 판별 (youtube.com / youtu.be)."""
    t = text.strip().lower()
    return "youtube.com/" in t or "youtu.be/" in t


def youtube_id(url: str) -> str:
    """유튜브 URL 에서 영상 ID 추출. 실패 시 빈 문자열 (순수 함수)."""
    patterns = [
        r"[?&]v=([A-Za-z0-9_-]{11})",       # watch?v=ID
        r"youtu\.be/([A-Za-z0-9_-]{11})",   # youtu.be/ID
        r"/shorts/([A-Za-z0-9_-]{11})",     # shorts/ID
        r"/embed/([A-Za-z0-9_-]{11})",      # embed/ID
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return ""


def download_video(url: str, out_dir: str = ".", *, stem: str = "reference") -> str:
    """유튜브/웹 영상을 내려받아 로컬 파일 경로를 돌려줍니다 (yt-dlp 필요).

    Args:
        url: 유튜브/웹 영상 링크.
        out_dir: 저장 폴더.
        stem: 저장 파일 이름(확장자 제외).

    Returns:
        내려받은 영상 파일 경로.

    Raises:
        RuntimeError: yt-dlp 가 없거나 다운로드에 실패한 경우.
    """
    import glob
    import shutil
    import subprocess

    if not shutil.which("yt-dlp"):
        raise RuntimeError(
            "yt-dlp 가 필요합니다(유튜브 링크 다운로드). 설치: pip install yt-dlp "
            "(또는 https://github.com/yt-dlp/yt-dlp)."
        )
    os.makedirs(out_dir, exist_ok=True)
    out_tmpl = os.path.join(out_dir, f"{stem}.%(ext)s")

    # mp4 우선, 없으면 최상 화질. 너무 큰 4K 는 720p 로 제한(분석엔 충분, 빠름).
    cmd = [
        "yt-dlp",
        "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b",
        "--merge-output-format", "mp4",
        "-o", out_tmpl,
        url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"영상 다운로드 실패: {res.stderr.strip()[:300]}")

    matches = sorted(glob.glob(os.path.join(out_dir, f"{stem}.*")))
    if not matches:
        raise RuntimeError("다운로드는 됐지만 결과 파일을 찾지 못했습니다.")
    return matches[0]


def resolve_reference(reference: str, out_dir: str = ".") -> str:
    """`--reference` 값을 실제 로컬 파일 경로로 해석합니다.

    링크면 내려받고, 이미 로컬 파일이면 그대로 돌려줍니다.
    """
    if is_url(reference):
        return download_video(reference, out_dir)
    if not os.path.isfile(reference):
        raise FileNotFoundError(f"참고 영상을 찾을 수 없습니다: {reference}")
    return reference
