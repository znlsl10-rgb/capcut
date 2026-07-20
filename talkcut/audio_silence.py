"""무음 감지 → 보존 구간 계산.

핵심 로직(프레임 RMS → 무음 구간 → 보존 구간)은 numpy 배열 위에서 도는
순수 함수라 오디오 파일 없이도 테스트됩니다. 파일 로딩만 soundfile/ffmpeg
를 지연 사용합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

Interval = Tuple[float, float]


@dataclass
class SilenceResult:
    duration: float
    silences: List[Interval] = field(default_factory=list)
    keeps: List[Interval] = field(default_factory=list)

    @property
    def removed(self) -> float:
        """제거되는 총 시간(초)."""
        kept = sum(e - s for s, e in self.keeps)
        return max(0.0, self.duration - kept)


def _rms_db_frames(samples, sr: int, frame_ms: float, hop_ms: float):
    """프레임별 RMS(dB) 배열과 프레임 시작 시각을 반환."""
    import numpy as np  # noqa: WPS433

    frame = max(1, int(sr * frame_ms / 1000.0))
    hop = max(1, int(sr * hop_ms / 1000.0))
    n = len(samples)
    if n == 0:
        return np.zeros(0), np.zeros(0)
    starts = list(range(0, n, hop))
    times = np.array([s / sr for s in starts], dtype=float)
    db = np.empty(len(starts), dtype=float)
    for i, s in enumerate(starts):
        seg = samples[s : s + frame]
        rms = float(np.sqrt(np.mean(seg.astype("float64") ** 2))) if len(seg) else 0.0
        db[i] = 20.0 * np.log10(rms + 1e-10)
    return times, db


def silences_from_db(
    times: Sequence[float],
    db: Sequence[float],
    *,
    frame_s: float,
    threshold_db: float,
    min_silence: float,
) -> List[Interval]:
    """RMS(dB) 배열에서 무음 구간을 찾습니다 (순수 함수).

    threshold_db 보다 조용한 프레임이 min_silence 초 이상 연속되면 무음으로 판정.
    """
    n = len(db)
    out: List[Interval] = []
    i = 0
    while i < n:
        if db[i] < threshold_db:
            j = i
            while j < n and db[j] < threshold_db:
                j += 1
            start = float(times[i])
            end = float(times[j - 1]) + frame_s
            if end - start >= min_silence:
                out.append((round(start, 3), round(end, 3)))
            i = j
        else:
            i += 1
    return out


def keep_segments(
    silences: Sequence[Interval],
    duration: float,
    *,
    pad: float = 0.06,
    min_keep: float = 0.20,
) -> List[Interval]:
    """무음 구간의 여집합(=보존 구간)을 만듭니다 (순수 함수).

    - 각 보존 구간 양끝을 `pad` 초 만큼 무음 쪽으로 넓혀 말 시작/끝이 잘리지 않게.
    - 패딩으로 겹치면 병합.
    - `min_keep` 보다 짧은 조각은 버림.
    """
    if duration <= 0:
        return []
    ordered = sorted((max(0.0, s), min(duration, e)) for s, e in silences if e > s)

    raw: List[List[float]] = []
    cursor = 0.0
    for s, e in ordered:
        if s > cursor:
            raw.append([cursor, s])
        cursor = max(cursor, e)
    if cursor < duration:
        raw.append([cursor, duration])

    padded = [[max(0.0, a - pad), min(duration, b + pad)] for a, b in raw]

    merged: List[List[float]] = []
    for a, b in padded:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    return [(round(a, 3), round(b, 3)) for a, b in merged if (b - a) >= min_keep]


def load_audio_mono(path: str, target_sr: int = 16000):
    """오디오를 모노 float32 로 로드합니다. (samples, sr) 반환.

    soundfile(wav/flac 등) → 실패 시 ffmpeg 로 wav 디코딩. mp4/mov 는 ffmpeg 필요.
    """
    import numpy as np  # noqa: WPS433

    try:
        import soundfile as sf  # noqa: WPS433

        data, sr = sf.read(path, dtype="float32", always_2d=False)
        if getattr(data, "ndim", 1) > 1:
            data = data.mean(axis=1)
        return np.asarray(data, dtype="float32"), int(sr)
    except Exception:  # noqa: BLE001 — 비오디오 컨테이너면 ffmpeg 로.
        pass

    import os  # noqa: WPS433
    import subprocess  # noqa: WPS433
    import tempfile  # noqa: WPS433

    import soundfile as sf  # noqa: WPS433

    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", str(target_sr), "-vn", tmp],
            check=True,
            capture_output=True,
        )
        data, sr = sf.read(tmp, dtype="float32", always_2d=False)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    if getattr(data, "ndim", 1) > 1:
        data = data.mean(axis=1)
    return np.asarray(data, dtype="float32"), int(sr)


def analyze_silence(
    path: str,
    *,
    threshold_db: float = -35.0,
    min_silence: float = 0.35,
    frame_ms: float = 30.0,
    hop_ms: float = 10.0,
    pad: float = 0.06,
    min_keep: float = 0.20,
) -> SilenceResult:
    """오디오 파일에서 무음 구간과 보존 구간을 계산합니다."""
    samples, sr = load_audio_mono(path)
    duration = len(samples) / sr if sr else 0.0
    times, db = _rms_db_frames(samples, sr, frame_ms, hop_ms)
    silences = silences_from_db(
        times, db, frame_s=hop_ms / 1000.0,
        threshold_db=threshold_db, min_silence=min_silence,
    )
    keeps = keep_segments(silences, duration, pad=pad, min_keep=min_keep)
    return SilenceResult(duration=round(duration, 3), silences=silences, keeps=keeps)
