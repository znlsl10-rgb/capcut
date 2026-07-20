"""talkcut 순수 로직 테스트 (오디오/pyCapCut 불필요)."""

import numpy as np

from talkcut.audio_silence import (
    SilenceResult,
    _rms_db_frames,
    keep_segments,
    silences_from_db,
)
from talkcut.osdetect import decide_track


# --- OS → 트랙 결정 ------------------------------------------------------
def test_track_mac_arm():
    track, backend, _ = decide_track("Darwin", "arm64")
    assert track == "A" and backend == "mlx-whisper"


def test_track_windows():
    track, backend, _ = decide_track("Windows", "AMD64")
    assert track == "C" and backend == "faster-whisper"


def test_track_intel_mac():
    track, backend, _ = decide_track("Darwin", "x86_64")
    assert track == "fallback" and backend == "faster-whisper"


def test_track_linux_fallback():
    track, backend, _ = decide_track("Linux", "x86_64")
    assert track == "fallback" and backend == "faster-whisper"


# --- 무음 판정 (순수) ----------------------------------------------------
def test_silences_from_db_detects_quiet_run():
    # 10ms hop, 프레임 시각 0,0.01,...  0.3~0.6s 구간이 조용함
    hop = 0.01
    times = [round(i * hop, 3) for i in range(100)]  # 0 ~ 0.99s
    db = [-10.0] * 100
    for i in range(30, 60):  # 0.30 ~ 0.60
        db[i] = -50.0
    sil = silences_from_db(times, db, frame_s=hop, threshold_db=-35, min_silence=0.2)
    assert len(sil) == 1
    s, e = sil[0]
    assert abs(s - 0.30) < 0.02 and abs(e - 0.60) < 0.02


def test_silences_min_length_filters_short():
    hop = 0.01
    times = [round(i * hop, 3) for i in range(100)]
    db = [-10.0] * 100
    for i in range(30, 34):  # 0.04s 짧은 무음
        db[i] = -50.0
    sil = silences_from_db(times, db, frame_s=hop, threshold_db=-35, min_silence=0.2)
    assert sil == []


# --- 보존 구간 (순수) ----------------------------------------------------
def test_keep_segments_complement():
    # 길이 10s, 무음 [3,4], [7,8] → 보존 [0,3],[4,7],[8,10]
    keeps = keep_segments([(3, 4), (7, 8)], duration=10.0, pad=0.0, min_keep=0.1)
    assert keeps == [(0.0, 3.0), (4.0, 7.0), (8.0, 10.0)]


def test_keep_segments_padding_and_merge():
    # 무음이 좁으면 패딩이 겹쳐 병합될 수 있음
    keeps = keep_segments([(2.0, 2.1)], duration=5.0, pad=0.2, min_keep=0.1)
    # [0,2]+pad → [0,2.2], [2.1,5]+pad → [1.9,5] → 겹쳐 [0,5] 로 병합
    assert keeps == [(0.0, 5.0)]


def test_keep_segments_drops_tiny():
    # [4.9,5.0] 보존은 0.1s < min_keep 0.2 → 버림
    keeps = keep_segments([(0.0, 4.9)], duration=5.0, pad=0.0, min_keep=0.2)
    assert keeps == []


def test_keep_no_silence_keeps_whole():
    keeps = keep_segments([], duration=8.0, pad=0.05, min_keep=0.2)
    assert keeps == [(0.0, 8.0)]


# --- RMS 프레임 (순수, numpy) --------------------------------------------
def test_rms_db_frames_loud_vs_quiet():
    sr = 1000
    loud = np.ones(500, dtype="float32") * 0.5
    quiet = np.ones(500, dtype="float32") * 1e-4
    samples = np.concatenate([loud, quiet])
    times, db = _rms_db_frames(samples, sr, frame_ms=30, hop_ms=10)
    # 앞부분은 큰 dB, 뒷부분은 작은 dB
    assert db[5] > -10
    assert db[-5] < -60


def test_silence_result_removed():
    r = SilenceResult(duration=10.0, silences=[(3, 5)], keeps=[(0, 3), (5, 10)])
    assert abs(r.removed - 2.0) < 1e-6
