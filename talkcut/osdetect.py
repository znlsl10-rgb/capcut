"""Step 0: OS 감지 + ASR 트랙 결정 + 환경 점검.

트랙 매핑:
  Darwin arm64      → A (Mac M칩, mlx-whisper 권장)
  Windows AMD64     → C (faster-whisper, MP4 export 보너스)
  Darwin x86_64/기타 → fallback (faster-whisper)
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Environment:
    system: str          # "Darwin" / "Windows" / "Linux"
    machine: str         # "arm64" / "AMD64" / "x86_64" ...
    track: str           # "A" / "C" / "fallback"
    asr_backend: str     # "mlx-whisper" / "faster-whisper"
    notes: str = ""
    missing_tools: List[str] = field(default_factory=list)
    install_hints: List[str] = field(default_factory=list)
    draft_folder: Optional[str] = None

    @property
    def ready(self) -> bool:
        return not self.missing_tools and self.draft_folder is not None


def decide_track(system: str, machine: str) -> tuple[str, str, str]:
    """(track, asr_backend, notes) 결정 (순수 함수)."""
    sys_l = (system or "").lower()
    mac_l = (machine or "").lower()
    if sys_l == "darwin" and mac_l in ("arm64", "aarch64"):
        return "A", "mlx-whisper", "Mac M칩 — mlx-whisper 가속"
    if sys_l.startswith("win") and mac_l in ("amd64", "x86_64"):
        return "C", "faster-whisper", "Windows — faster-whisper (+MP4 export 보너스)"
    if sys_l == "darwin":
        return "fallback", "faster-whisper", "Intel Mac — faster-whisper 폴백"
    return "fallback", "faster-whisper", f"{system} {machine} — faster-whisper 폴백"


def _install_hints(system: str, missing: List[str]) -> List[str]:
    sys_l = (system or "").lower()
    hints: List[str] = []
    if "ffmpeg" in missing:
        if sys_l == "darwin":
            hints.append("brew install ffmpeg")
        elif sys_l.startswith("win"):
            hints.append("winget install ffmpeg")
        else:
            hints.append("sudo apt install ffmpeg")
    return hints


def check_environment(*, check_draft_folder: bool = True) -> Environment:
    """현재 머신 환경을 점검합니다.

    빠진 도구가 있으면 `missing_tools`/`install_hints` 에 채워 반환합니다.
    (spec: 설치 명령만 알려주고 대기)
    """
    system = platform.system()
    machine = platform.machine()
    track, backend, notes = decide_track(system, machine)

    missing: List[str] = []
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")

    draft_folder: Optional[str] = None
    if check_draft_folder:
        try:
            from capcut_agent.capcut_paths import default_draft_folder

            draft_folder = default_draft_folder()
        except Exception:  # noqa: BLE001
            draft_folder = None

    return Environment(
        system=system,
        machine=machine,
        track=track,
        asr_backend=backend,
        notes=notes,
        missing_tools=missing,
        install_hints=_install_hints(system, missing),
        draft_folder=draft_folder,
    )


def format_report(env: Environment) -> str:
    lines = [
        f"[OS] {env.system} {env.machine} → 트랙 {env.track} ({env.notes})",
        f"[ASR] {env.asr_backend}",
    ]
    lines.append(
        f"[캡컷 초안폴더] {env.draft_folder}" if env.draft_folder
        else "[캡컷 초안폴더] 미발견 — 캡컷 설치 후 1회 실행하거나 --draft-folder 로 지정"
    )
    if env.missing_tools:
        lines.append(f"[빠진 도구] {', '.join(env.missing_tools)}")
        for h in env.install_hints:
            lines.append(f"    설치: {h}")
    else:
        lines.append("[도구] ffmpeg OK")
    return "\n".join(lines)
