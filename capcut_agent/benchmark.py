"""참고 영상 분석 · 벤치마킹.

잘 만든 **참고 영상**을 하나 주면 그 영상의 "편집 레시피"를 뽑아내고
(`analyze_reference`), 그 레시피를 내 **로컬 클립**에 적용해 유사한 느낌의
영상을 만들도록 설정을 변환합니다(`profile_to_overrides`).

벤치마킹하는 3요소:
  - **컷편집** : 장면 전환(scene cut) 시각을 감지해 컷 속도(분당 컷 수)·평균 컷
    길이를 재고, 그로부터 전환 간격/소재 모드를 정합니다.
  - **음악**   : 참고 영상의 오디오 템포(BPM)·에너지를 재서 스타일 프리셋을
    고릅니다. 원한다면 참고 영상의 오디오를 그대로 사운드트랙으로 씁니다.
  - **자막**   : 프레임을 샘플링해 화면에 고정으로 떠 있는 자막 밴드(세로 위치)를
    추정하고, 내 영상 자막을 같은 높이에 놓습니다.

설계 원칙은 프로젝트 전체와 동일합니다 — **순수 로직(통계·스타일 도출·설정
변환)은 무거운 의존성 없이 테스트 가능**하고, ffmpeg/librosa 를 쓰는 실제
추출 함수만 지연 임포트로 분리합니다.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# 데이터 구조
# --------------------------------------------------------------------------
@dataclass
class CutStats:
    """참고 영상의 컷 편집 통계.

    Attributes:
        cut_times: 감지된 장면 전환 시각(초) 오름차순.
        duration: 영상 길이(초).
        count: 컷 개수(= 장면 개수는 count+1).
        cuts_per_min: 분당 컷 수(편집 속도 지표).
        median_cut: 컷 사이 간격 중앙값(초).
        mean_cut: 컷 사이 간격 평균(초).
        p25_cut: 컷 간격 25 분위(짧은 컷 쪽 대표값).
        fastest_cut: 가장 짧은 컷 간격(초).
    """

    cut_times: List[float] = field(default_factory=list)
    duration: float = 0.0
    count: int = 0
    cuts_per_min: float = 0.0
    median_cut: float = 0.0
    mean_cut: float = 0.0
    p25_cut: float = 0.0
    fastest_cut: float = 0.0


@dataclass
class SubtitleProfile:
    """참고 영상의 자막 배치 추정.

    Attributes:
        present: 자막(고정 텍스트 밴드)이 있다고 판단되는지.
        vertical_pos: 자막 밴드 중심의 세로 위치 0(위)~1(아래).
        band: 위치 구간 라벨("upper"/"center"/"lower"/"none").
        contrast: 밴드 대비 강도(주변 대비 배수). 판정 신뢰도 근사.
        frames_sampled: 샘플링한 프레임 수.
    """

    present: bool = False
    vertical_pos: float = 0.85
    band: str = "lower"
    contrast: float = 0.0
    frames_sampled: int = 0


@dataclass
class BenchmarkProfile:
    """참고 영상에서 추출한 편집 레시피.

    `to_dict()` 로 JSON 저장이 가능하고, `benchmark.profile_to_overrides()` 로
    `AgentConfig` 필드 오버라이드를 만들 수 있습니다.
    """

    source: str
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration: float = 0.0
    aspect: str = "vertical"          # vertical | square | horizontal
    has_audio: bool = False
    tempo: float = 0.0                 # 참고 오디오 BPM(0=미측정)
    cuts: CutStats = field(default_factory=CutStats)
    subtitles: SubtitleProfile = field(default_factory=SubtitleProfile)
    style: str = "goosebump"          # 도출된 스타일 프리셋

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


# --------------------------------------------------------------------------
# 순수 로직 (의존성 없이 테스트 가능)
# --------------------------------------------------------------------------
def classify_aspect(width: int, height: int) -> str:
    """가로세로 비율을 vertical/square/horizontal 로 분류."""
    if width <= 0 or height <= 0:
        return "vertical"
    ratio = width / height
    if ratio <= 0.9:
        return "vertical"
    if ratio >= 1.2:
        return "horizontal"
    return "square"


def output_dimensions(aspect: str, width: int, height: int) -> tuple:
    """벤치마크 출력 해상도. 참고 영상 비율을 표준 캔버스로 맞춥니다.

    세로 1080x1920 / 정사각 1080x1080 / 가로 1920x1080. 참고 해상도가 이미
    표준이면 그대로 씁니다.
    """
    presets = {
        "vertical": (1080, 1920),
        "square": (1080, 1080),
        "horizontal": (1920, 1080),
    }
    if width > 0 and height > 0 and classify_aspect(width, height) == aspect:
        return width, height
    return presets.get(aspect, (1080, 1920))


def compute_cut_stats(cut_times: List[float], duration: float) -> CutStats:
    """장면 전환 시각 목록으로부터 컷 통계를 계산 (순수 함수).

    컷 간격은 [0, cut1, cut2, ..., duration] 의 인접 차이로 봅니다.
    """
    cuts = sorted(t for t in cut_times if 0.0 < t < duration)
    if duration <= 0:
        return CutStats(cut_times=cuts)

    marks = [0.0] + cuts + [duration]
    gaps = [b - a for a, b in zip(marks, marks[1:]) if b - a > 1e-6]
    if not gaps:
        return CutStats(cut_times=cuts, duration=round(duration, 3))

    cpm = len(cuts) / (duration / 60.0) if duration > 0 else 0.0
    return CutStats(
        cut_times=[round(t, 3) for t in cuts],
        duration=round(duration, 3),
        count=len(cuts),
        cuts_per_min=round(cpm, 2),
        median_cut=round(statistics.median(gaps), 3),
        mean_cut=round(statistics.fmean(gaps), 3),
        p25_cut=round(_quantile(gaps, 0.25), 3),
        fastest_cut=round(min(gaps), 3),
    )


def _quantile(values: List[float], q: float) -> float:
    """0~1 분위수(선형 보간). numpy 없이 순수 계산."""
    if not values:
        return 0.0
    q = min(max(q, 0.0), 1.0)
    ordered = sorted(values)
    idx = q * (len(ordered) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def derive_style(tempo: float, cuts_per_min: float, median_cut: float) -> str:
    """템포·컷 속도로부터 스타일 프리셋을 도출 (순수 함수).

    규칙(대략):
      - 매우 빠른 컷(분당 30+ 또는 컷 1.2s 이하) + 빠른 템포 → energetic
      - 빠른 편집 전반 → goosebump(소름, 기본 리듬 컷)
      - 느린 컷(컷 3s+ 이며 분당 12 이하) + 느린 템포 → dreamy
    """
    fast_cut = cuts_per_min >= 30 or (0 < median_cut <= 1.2)
    slow_cut = median_cut >= 3.0 and (cuts_per_min == 0 or cuts_per_min <= 12)
    fast_tempo = tempo >= 120
    slow_tempo = 0 < tempo <= 95

    if fast_cut and (fast_tempo or tempo == 0):
        return "energetic"
    if slow_cut and (slow_tempo or tempo == 0):
        return "dreamy"
    if cuts_per_min >= 18 or (0 < median_cut <= 2.2):
        return "goosebump"
    if slow_cut:
        return "dreamy"
    return "goosebump"


def recommended_min_gap(median_cut: float) -> float:
    """컷 간격 중앙값으로부터 전환 최소 간격(초)을 정합니다.

    새 영상은 자기 음악의 비트에 컷을 놓되, 참고 영상만큼 촘촘하게(또는
    성글게) 끊기도록 최소 간격을 맞춥니다. 0.3~3.5s 로 클램프.
    """
    if median_cut <= 0:
        return 0.45
    return round(min(3.5, max(0.3, median_cut * 0.85)), 3)


def recommended_footage_mode(median_cut: float, cuts_per_min: float) -> str:
    """컷 속도로부터 소재 모드를 정합니다.

    빠른 편집이면 비트 몽타주(beat), 느린 편집이면 커버리지(슬로우 채움).
    애매하면 auto.
    """
    if cuts_per_min >= 24 or (0 < median_cut <= 1.6):
        return "beat"
    if median_cut >= 3.0:
        return "coverage"
    return "auto"


def subtitle_transform_y(vertical_pos: float) -> float:
    """자막 밴드 세로 위치(0=위,1=아래) → CapCut transform_y.

    CapCut 은 화면 아래가 음수, 위가 양수(중앙 0)입니다. draft_builder 의
    기본 하단 자막이 -0.72 인 것과 일관됩니다. 화면 밖으로 나가지 않도록
    [-0.85, 0.6] 로 클램프.
    """
    ty = 1.0 - 2.0 * min(max(vertical_pos, 0.0), 1.0)
    return round(min(0.6, max(-0.85, ty)), 3)


def locate_text_band(row_energy: List[float]) -> SubtitleProfile:
    """행별 텍스트 에너지 프로파일에서 자막 밴드를 찾습니다 (순수 함수).

    `row_energy[i]` 는 프레임들 평균의 i 번째 가로줄 텍스트성(가로 대비) 에너지.
    자막은 여러 프레임에 걸쳐 같은 줄에 떠 있으므로 그 줄들이 두드러집니다.

    판정:
      - 최고 에너지 줄을 peak 로, 그 주변에서 (median 위로) 이어지는 밴드를 확장.
      - peak 가 median 의 1.6 배 이상이면 자막 있음으로 판단.
      - 밴드 중심의 세로 위치(0~1)와 대비 배수를 돌려줍니다.
    """
    n = len(row_energy)
    if n < 4:
        return SubtitleProfile(present=False)

    med = statistics.median(row_energy)
    peak = max(row_energy)
    peak_idx = row_energy.index(peak)
    contrast = (peak / med) if med > 1e-9 else 0.0

    # peak 주변에서 (median + 절반 문턱) 이상으로 이어지는 밴드 확장.
    thr = med + 0.5 * (peak - med)
    lo = hi = peak_idx
    while lo - 1 >= 0 and row_energy[lo - 1] >= thr:
        lo -= 1
    while hi + 1 < n and row_energy[hi + 1] >= thr:
        hi += 1
    center = (lo + hi) / 2.0
    vertical_pos = center / (n - 1)

    present = contrast >= 1.6
    if vertical_pos < 0.34:
        band = "upper"
    elif vertical_pos < 0.66:
        band = "center"
    else:
        band = "lower"
    return SubtitleProfile(
        present=present,
        vertical_pos=round(vertical_pos, 3),
        band=band if present else "none",
        contrast=round(contrast, 3),
    )


def profile_to_overrides(
    profile: BenchmarkProfile,
    *,
    style_override: Optional[str] = None,
) -> Dict[str, Any]:
    """벤치마크 프로파일 → AgentConfig 필드 오버라이드 dict.

    반환 dict 를 `setattr` 로 config 에 얹으면 참고 영상과 유사한 편집이
    됩니다. 자막 세로 위치는 draft_builder 가 읽도록 `extra['subtitle_y']` 로
    전달합니다.
    """
    width, height = output_dimensions(profile.aspect, profile.width, profile.height)
    overrides: Dict[str, Any] = {
        "width": width,
        "height": height,
        "style": style_override or profile.style,
        "min_transition_gap": recommended_min_gap(profile.cuts.median_cut),
        "footage_mode": recommended_footage_mode(
            profile.cuts.median_cut, profile.cuts.cuts_per_min
        ),
    }
    extra: Dict[str, Any] = {"benchmark_source": profile.source}
    if profile.subtitles.present:
        extra["subtitle_y"] = subtitle_transform_y(profile.subtitles.vertical_pos)
    overrides["extra"] = extra
    return overrides


def summarize_profile(profile: BenchmarkProfile) -> str:
    """사람이 읽는 벤치마크 요약(라이브러리 불필요)."""
    c = profile.cuts
    s = profile.subtitles
    aspect_ko = {"vertical": "세로", "square": "정사각", "horizontal": "가로"}
    lines = [
        f"🔬 참고 영상 분석 — {profile.source}",
        f"   포맷    {profile.width}x{profile.height} · "
        f"{aspect_ko.get(profile.aspect, profile.aspect)} · "
        f"{profile.fps:.0f}fps · {profile.duration:.1f}s"
        + ("  · 오디오 있음" if profile.has_audio else "  · 오디오 없음"),
        f"   음악    {'~%.0f BPM' % profile.tempo if profile.tempo else '템포 미측정'}",
        f"   컷편집  {c.count}컷 · 분당 {c.cuts_per_min:.1f}컷 · "
        f"컷 길이 중앙값 {c.median_cut:.2f}s (최단 {c.fastest_cut:.2f}s)",
    ]
    if s.present:
        band_ko = {"upper": "상단", "center": "중앙", "lower": "하단"}
        lines.append(
            f"   자막    {band_ko.get(s.band, s.band)} 밴드 "
            f"(세로 {s.vertical_pos:.2f} · 대비 {s.contrast:.1f}x)"
        )
    else:
        lines.append("   자막    감지 안 됨(또는 미분석) → 하단 기본값 사용")
    lines.append(
        f"   ⇒ 벤치마크 스타일 '{profile.style}' · "
        f"전환간격 ~{recommended_min_gap(c.median_cut):.2f}s · "
        f"소재모드 {recommended_footage_mode(c.median_cut, c.cuts_per_min)}"
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 실제 추출 (ffmpeg / ffprobe / librosa — 지연 임포트)
# --------------------------------------------------------------------------
def probe_video(path: str) -> Dict[str, Any]:
    """ffprobe 로 해상도/fps/길이/오디오 유무를 읽습니다.

    Returns dict(width, height, fps, duration, has_audio).
    ffprobe 가 없거나 실패하면 RuntimeError.
    """
    import shutil
    import subprocess

    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe 를 찾을 수 없습니다. ffmpeg 를 설치하세요.")

    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {out.stderr.strip()[:200]}")
    data = json.loads(out.stdout or "{}")

    width = height = 0
    fps = 0.0
    has_audio = False
    for st in data.get("streams", []):
        if st.get("codec_type") == "video" and not width:
            width = int(st.get("width", 0) or 0)
            height = int(st.get("height", 0) or 0)
            fps = _parse_fraction(st.get("avg_frame_rate") or st.get("r_frame_rate"))
        elif st.get("codec_type") == "audio":
            has_audio = True
    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    return {
        "width": width, "height": height, "fps": fps,
        "duration": duration, "has_audio": has_audio,
    }


def _parse_fraction(text: Optional[str]) -> float:
    """'30000/1001' 같은 프레임레이트 문자열 → float."""
    if not text:
        return 0.0
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(text)
    except (ValueError, ZeroDivisionError):
        return 0.0


def detect_scene_cuts(path: str, threshold: float = 0.27) -> List[float]:
    """ffmpeg scene 필터로 장면 전환 시각(초) 목록을 감지합니다.

    `select='gt(scene,threshold)'` 로 장면 변화가 큰 프레임만 통과시키고
    showinfo 로 그 프레임들의 pts_time 을 뽑습니다. 컷이 거의 없으면
    문턱을 낮춰 한 번 더 시도합니다.
    """
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 를 찾을 수 없습니다. ffmpeg 를 설치하세요.")

    def _run(thr: float) -> List[float]:
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats", "-i", path,
            "-filter:v", f"select='gt(scene,{thr})',showinfo",
            "-an", "-f", "null", "-",
        ]
        out = subprocess.run(cmd, capture_output=True, text=True)
        times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", out.stderr)]
        return sorted(set(round(t, 3) for t in times))

    cuts = _run(threshold)
    if len(cuts) < 2 and threshold > 0.15:
        cuts = _run(0.15)
    return cuts


def measure_tempo(path: str) -> float:
    """참고 영상의 오디오 트랙을 뽑아 템포(BPM)를 잰다. 실패 시 0.0.

    ffmpeg 로 wav 를 임시 추출 → 기존 audio.analyze_audio 재사용.
    """
    import os
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("ffmpeg"):
        return 0.0
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", path,
               "-vn", "-ac", "1", "-ar", "22050", tmp.name]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or os.path.getsize(tmp.name) == 0:
            return 0.0
        from .audio import analyze_audio

        beatmap = analyze_audio(tmp.name)
        return round(float(beatmap.tempo), 2)
    except Exception:  # noqa: BLE001 — 템포는 부가정보, 실패해도 진행.
        return 0.0
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _sample_row_energy(path: str, duration: float,
                       sample_w: int = 120, sample_h: int = 200,
                       fps_sample: float = 1.0) -> List[float]:
    """프레임을 회색조 raw 로 뽑아 가로줄별 텍스트성 에너지를 계산합니다.

    ffmpeg 로 (sample_w x sample_h) 회색조 rawvideo 를 stdout 으로 받아
    numpy 로 각 프레임의 가로 방향 밝기 변화(|Δ가로|)를 줄별로 합산하고,
    프레임 전체에 대해 평균냅니다. 자막처럼 여러 프레임에 걸쳐 같은 줄에
    있는 고대비 텍스트가 그 줄의 에너지를 끌어올립니다.

    numpy 나 ffmpeg 가 없으면 빈 리스트를 돌려주고, 호출부는 '자막 미감지'로
    처리합니다.
    """
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return []
    try:
        import numpy as np
    except ImportError:
        return []

    vf = f"fps={fps_sample},scale={sample_w}:{sample_h},format=gray"
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
           "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    out = subprocess.run(cmd, capture_output=True)
    buf = out.stdout
    frame_size = sample_w * sample_h
    n_frames = len(buf) // frame_size
    if n_frames == 0:
        return []

    arr = np.frombuffer(buf[: n_frames * frame_size], dtype=np.uint8)
    arr = arr.reshape(n_frames, sample_h, sample_w).astype(np.float32)
    # 가로 방향 인접 차이의 절댓값 → 텍스트(글자 경계)에서 큼.
    grad = np.abs(np.diff(arr, axis=2))            # (frames, h, w-1)
    row_energy = grad.mean(axis=(0, 2))            # (h,)
    return [float(v) for v in row_energy]


def detect_subtitles(path: str, duration: float) -> SubtitleProfile:
    """참고 영상의 자막 밴드를 추정합니다(프레임 샘플링 + 순수 밴드 탐색)."""
    row_energy = _sample_row_energy(path, duration)
    if not row_energy:
        return SubtitleProfile(present=False, frames_sampled=0)
    profile = locate_text_band(row_energy)
    # 샘플 프레임 수는 대략 duration*fps_sample.
    profile.frames_sampled = max(1, int(duration)) if duration else 0
    return profile


def analyze_reference(
    path: str,
    *,
    detect_subs: bool = True,
    measure_music: bool = True,
    scene_threshold: float = 0.27,
) -> BenchmarkProfile:
    """참고 영상을 분석해 BenchmarkProfile 을 만듭니다 (지연 임포트).

    Args:
        path: 참고 영상 파일 경로.
        detect_subs: 자막 밴드 추정 여부(느릴 수 있음).
        measure_music: 오디오 템포 측정 여부.
        scene_threshold: 장면 전환 감지 민감도(작을수록 컷 많이 감지).
    """
    import os

    if not os.path.isfile(path):
        raise FileNotFoundError(f"참고 영상을 찾을 수 없습니다: {path}")

    info = probe_video(path)
    duration = info["duration"]
    cut_times = detect_scene_cuts(path, threshold=scene_threshold)
    cuts = compute_cut_stats(cut_times, duration)

    tempo = measure_tempo(path) if (measure_music and info["has_audio"]) else 0.0

    if detect_subs:
        subs = detect_subtitles(path, duration)
    else:
        subs = SubtitleProfile(present=False)

    aspect = classify_aspect(info["width"], info["height"])
    style = derive_style(tempo, cuts.cuts_per_min, cuts.median_cut)

    return BenchmarkProfile(
        source=path,
        width=info["width"],
        height=info["height"],
        fps=round(info["fps"], 3),
        duration=round(duration, 3),
        aspect=aspect,
        has_audio=info["has_audio"],
        tempo=tempo,
        cuts=cuts,
        subtitles=subs,
        style=style,
    )


def extract_reference_audio(path: str, out_path: str) -> str:
    """참고 영상의 오디오를 사운드트랙(wav)으로 추출합니다.

    `--use-reference-audio` 로 참고 영상의 음악을 그대로 쓸 때 사용합니다.
    """
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 를 찾을 수 없습니다. ffmpeg 를 설치하세요.")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", path,
           "-vn", "-ac", "2", "-ar", "44100", out_path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"오디오 추출 실패: {res.stderr.strip()[:200]}")
    return out_path
