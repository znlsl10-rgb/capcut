"""오디오 분석: 비트 · 온셋 · 에너지(드롭) 감지.

`analyze_audio()` 는 librosa 를 사용해 노래를 분석하고 `BeatMap` 을 만듭니다.
`select_transition_points()` 는 순수 함수로, 비트 정보로부터 실제 화면 전환
지점을 선정합니다(의존성 없이 테스트 가능).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence


@dataclass
class BeatMap:
    """노래의 리듬 분석 결과.

    Attributes:
        duration: 전체 길이(초).
        tempo: 추정 BPM.
        beats: 모든 비트 시각(초).
        strengths: 각 비트의 상대 세기 0~1 (len == len(beats)).
        downbeats: 강박(마디 첫 박) 추정 시각(초). 큰 전환에 사용.
    """

    duration: float
    tempo: float
    beats: List[float] = field(default_factory=list)
    strengths: List[float] = field(default_factory=list)
    downbeats: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.strengths and len(self.strengths) != len(self.beats):
            raise ValueError("strengths 길이는 beats 와 같아야 합니다.")


@dataclass
class TransitionPoint:
    """선정된 화면 전환 지점.

    Attributes:
        time: 전환이 일어나는 시각(초).
        strong: 강박/드롭 여부 (True 면 더 강렬한 전환 사용).
    """

    time: float
    strong: bool = False


def select_transition_points(
    beatmap: BeatMap,
    *,
    min_gap: float = 0.45,
    subdivision: int = 1,
    max_count: int = 0,
    strong_percentile: float = 0.7,
) -> List[TransitionPoint]:
    """비트 정보로부터 화면 전환 지점을 선정합니다 (순수 함수).

    규칙:
      - `subdivision` 개 비트마다 하나씩 후보로 사용(1=매 비트).
      - 직전 채택 지점과 `min_gap`(초) 미만이면 건너뜀(과도한 컷 방지).
      - downbeat 이거나 세기가 상위 `strong_percentile` 이면 strong=True.
      - `max_count` > 0 이면 세기 우선으로 상한을 적용.

    Args:
        beatmap: 분석 결과.
        min_gap: 전환 사이 최소 간격(초).
        subdivision: 비트 추출 간격(1=매 비트, 2=한 박 걸러 등).
        max_count: 최대 전환 수(0=무제한).
        strong_percentile: strong 판정 세기 분위수(0~1).

    Returns:
        시간순으로 정렬된 TransitionPoint 목록.
    """
    if subdivision < 1:
        raise ValueError("subdivision 은 1 이상이어야 합니다.")

    beats = beatmap.beats
    if not beats:
        return []

    strengths = beatmap.strengths or [1.0] * len(beats)
    downbeat_set = {round(t, 3) for t in beatmap.downbeats}

    threshold = _percentile(strengths, strong_percentile) if strengths else 1.0

    selected: List[TransitionPoint] = []
    last_time = -1e9
    for i in range(0, len(beats), subdivision):
        t = beats[i]
        if t <= 0 or t >= beatmap.duration:
            continue
        if t - last_time < min_gap:
            continue
        is_strong = round(t, 3) in downbeat_set or strengths[i] >= threshold
        selected.append(TransitionPoint(time=round(t, 3), strong=is_strong))
        last_time = t

    if max_count and len(selected) > max_count:
        # 세기 순으로 상위 max_count 만 유지하되 시간순 재정렬.
        order = sorted(
            range(len(selected)),
            key=lambda idx: (selected[idx].strong, _nearest_strength(beatmap, selected[idx].time)),
            reverse=True,
        )[:max_count]
        selected = [selected[i] for i in sorted(order)]

    return selected


def segment_boundaries(points: Sequence[TransitionPoint], duration: float) -> List[float]:
    """전환 지점으로부터 배경 클립 경계 리스트를 만듭니다.

    반환값은 [0.0, t1, t2, ..., duration] 형태이며, 인접 세그먼트 개수는
    len(points)+1 입니다.
    """
    bounds = [0.0]
    for p in points:
        if 0.0 < p.time < duration and p.time > bounds[-1]:
            bounds.append(round(p.time, 3))
    if not bounds or bounds[-1] < duration:
        bounds.append(round(duration, 3))
    return bounds


def _percentile(values: Sequence[float], q: float) -> float:
    """0~1 분위수. numpy 없이 순수 계산."""
    if not values:
        return 0.0
    q = min(max(q, 0.0), 1.0)
    ordered = sorted(values)
    idx = q * (len(ordered) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _nearest_strength(beatmap: BeatMap, time: float) -> float:
    if not beatmap.strengths:
        return 1.0
    best = 0.0
    best_d = 1e9
    for t, s in zip(beatmap.beats, beatmap.strengths):
        d = abs(t - time)
        if d < best_d:
            best_d, best = d, s
    return best


def analyze_audio(audio_path: str) -> BeatMap:
    """librosa 로 노래를 분석해 BeatMap 을 만듭니다 (지연 임포트).

    - beat_track 으로 템포와 비트 프레임을 얻고,
    - onset envelope 로 각 비트의 상대 세기를 계산하며,
    - 스펙트럼 대비(percussive) 로 강한 비트(드롭 근사)를 downbeat 로 둡니다.
    """
    import numpy as np  # noqa: WPS433
    import librosa  # noqa: WPS433

    y, sr = librosa.load(audio_path, sr=None, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))

    # 타악(percussive) 성분을 분리하면 비트/드롭이 더 또렷합니다.
    y_harm, y_perc = librosa.effects.hpss(y)
    onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr)

    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # 각 비트에서의 온셋 세기 → 0~1 정규화.
    if len(onset_env) > 0:
        beat_strengths = onset_env[np.clip(beat_frames, 0, len(onset_env) - 1)]
        max_s = float(beat_strengths.max()) if beat_strengths.size else 1.0
        strengths = [float(s) / max_s if max_s > 0 else 0.0 for s in beat_strengths]
    else:
        strengths = [1.0] * len(beat_times)

    # 상위 세기 비트를 강박(드롭 근사)으로 간주.
    downbeats: List[float] = []
    if strengths:
        thr = _percentile(strengths, 0.8)
        downbeats = [round(float(t), 3) for t, s in zip(beat_times, strengths) if s >= thr]

    return BeatMap(
        duration=duration,
        tempo=float(np.atleast_1d(tempo)[0]),
        beats=[round(float(t), 3) for t in beat_times],
        strengths=strengths,
        downbeats=downbeats,
    )
