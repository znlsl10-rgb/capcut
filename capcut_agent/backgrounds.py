"""무드 기반 배경 자동 생성.

배경 footage 없이도 뮤직비디오가 되도록, 곡 무드에 맞는 그라디언트 배경
클립(이미지)을 자동 생성합니다. 비트 컷·줌·전환이 얹히면 정지 이미지여도
리듬감 있게 화면이 바뀝니다.

`backgrounds/<무드>/` 폴더에 실제 클립이 있으면 그것을 우선 사용합니다.
그라디언트 생성은 표준 라이브러리(zlib/struct)만 사용 — 추가 의존성 없음.
"""

from __future__ import annotations

import glob
import os
import struct
import zlib
from typing import List, Tuple

from .songbook import MOOD_BACKGROUND

# 무드 → 대표 베이스 색(그라디언트 중심). 분위기 가이드의 색감 톤 반영.
MOOD_BASE_HEX = {
    "각성": "#12306E",  # 딥 블루
    "버팀": "#14524E",  # 차분한 틸
    "확신": "#7A521E",  # 앰버
    "도약": "#2E6BC2",  # 밝은 블루-화이트
    "도착": "#7A5E1E",  # 따뜻한 골드
    "위로": "#3A4048",  # 뮤트 그레이
}
DEFAULT_BASE_HEX = "#12306E"


def _hex(c: str) -> Tuple[int, int, int]:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _clip(v: int) -> int:
    return max(0, min(255, v))


def _write_gradient_png(path: str, w: int, h: int,
                        top: Tuple[int, int, int], bottom: Tuple[int, int, int]) -> None:
    """세로 그라디언트 PNG 를 씁니다(표준 라이브러리)."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = bytearray()
    for y in range(h):
        t = y / max(1, h - 1)
        r = _clip(round(top[0] + (bottom[0] - top[0]) * t))
        g = _clip(round(top[1] + (bottom[1] - top[1]) * t))
        b = _clip(round(top[2] + (bottom[2] - top[2]) * t))
        raw.append(0)  # 필터 바이트
        raw += bytes((r, g, b)) * w
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def _variants(base: Tuple[int, int, int], n: int) -> List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]:
    """베이스 색에서 n개의 (top,bottom) 그라디언트 쌍을 만듭니다.

    밝기·색조를 조금씩 바꿔 컷마다 미묘하게 다른 배경이 되게 합니다.
    """
    r, g, b = base
    dark = (_clip(r - 40), _clip(g - 40), _clip(b - 40))
    out: List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = []
    for i in range(n):
        # 밝기 오프셋 + 미세 색조 회전
        k = (i - n / 2) * 10
        top = (_clip(int(r + k)), _clip(int(g + k * 0.6)), _clip(int(b + k * 1.2)))
        bot = (_clip(int(dark[0] + k * 0.4)), _clip(int(dark[1] + k * 0.3)), _clip(int(dark[2] + k)))
        if i % 2:  # 방향 번갈아
            top, bot = bot, top
        out.append((top, bot))
    return out


def library_clips(mood: str, root: str = "backgrounds") -> List[str]:
    """backgrounds/<무드>/ 폴더의 실제 클립 목록(있으면)."""
    folder = os.path.join(root, mood)
    if not os.path.isdir(folder):
        return []
    exts = ("mp4", "mov", "mkv", "webm", "jpg", "jpeg", "png", "gif")
    found: List[str] = []
    for e in exts:
        found += glob.glob(os.path.join(folder, f"*.{e}"))
        found += glob.glob(os.path.join(folder, f"*.{e.upper()}"))
    return sorted(found)


def auto_background_clips(
    mood: str,
    out_dir: str,
    *,
    count: int = 6,
    width: int = 720,
    height: int = 1280,
    library_root: str = "backgrounds",
) -> List[str]:
    """무드에 맞는 배경 클립 경로 목록을 돌려줍니다.

    우선순위: backgrounds/<무드>/ 실제 클립 → 없으면 그라디언트 자동 생성.

    Args:
        mood: 곡 무드(각성/버팀/…).
        out_dir: 생성 이미지를 저장할 폴더.
        count: 생성할 배경 개수(비트 컷마다 순환).
    """
    lib = library_clips(mood, library_root)
    if lib:
        return lib

    os.makedirs(out_dir, exist_ok=True)
    base = _hex(MOOD_BASE_HEX.get(mood, DEFAULT_BASE_HEX))
    paths: List[str] = []
    for i, (top, bot) in enumerate(_variants(base, count), 1):
        p = os.path.join(out_dir, f"bg_{mood}_{i:02d}.png")
        if not os.path.exists(p):
            _write_gradient_png(p, width, height, top, bot)
        paths.append(p)
    return paths
