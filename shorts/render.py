"""헤드리스 렌더러 — 나레이션 + 내 소재 + 자막 → 세로 mp4 (ffmpeg).

캡컷 앱 없이 서버/클라우드에서 **완전 무인**으로 완성 mp4 를 뽑습니다. 그래야
주제→대본→TTS→렌더→틱톡 업로드까지 사람 손 없이 이어집니다.

파이프라인:
    1) 나레이션 길이만큼 배경 타임라인을 자막 경계에 맞춰 컷으로 분할
    2) 각 컷: 내 소재를 세로(1080x1920)로 cover-crop, 영상은 트림/루프, 이미지는 슬로우 줌
    3) 컷들을 이어붙여 배경 영상 생성(동일 코덱 → 무손실 concat)
    4) ASS 자막(굵은 한글, 외곽선/그림자)을 구워 넣고 나레이션 오디오를 얹어 출력

ffmpeg 바이너리는 `imageio-ffmpeg` 정적 바이너리를 우선 사용하므로 시스템 설치가
없어도 동작합니다. 순수 로직(타임라인 계획 · ASS 생성)은 ffmpeg 없이 테스트됩니다.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

# 한글 자막 기본 폰트(설치되어 있으면 사용). 없으면 fontconfig 가 대체.
DEFAULT_FONT = "Noto Sans CJK KR"

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass
class Caption:
    """구워 넣을 자막 한 줄."""

    start: float
    end: float
    text: str


@dataclass
class RenderStyle:
    """세로 쇼츠 렌더 스타일(자막/배경)."""

    width: int = 1080
    height: int = 1920
    fps: int = 30
    font: str = DEFAULT_FONT
    font_size: int = 90          # 1080 폭 기준 굵고 큼
    primary: str = "#FFFFFF"     # 자막 글자색
    outline: str = "#000000"     # 외곽선
    outline_w: int = 6
    shadow: int = 3
    margin_v: int = 420          # 하단에서 위로(세로 화면 중하단에 안착)
    ken_burns: bool = False      # 이미지 슬로우 줌(zoompan). CPU 매우 무거움 → 기본 OFF
    bg_music_volume: float = 0.0  # (예약) 배경음악 볼륨


# --- ffmpeg 위치 -------------------------------------------------------------

def ffmpeg_exe() -> str:
    """사용할 ffmpeg 실행 경로. imageio-ffmpeg 정적 바이너리 우선."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def _run(cmd: Sequence[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"ffmpeg 실패 (code {proc.returncode}):\n{tail}")


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")


def media_duration(path: str) -> Optional[float]:
    """미디어 길이(초). 알 수 없으면 None. ffmpeg -i stderr 파싱."""
    proc = subprocess.run([ffmpeg_exe(), "-i", path], capture_output=True, text=True)
    m = _DUR_RE.search(proc.stderr)
    if not m:
        return None
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTS


# --- 타임라인 계획(순수 함수) ------------------------------------------------

def plan_blocks(
    captions: Sequence[Caption],
    total: float,
    *,
    min_seg: float = 1.2,
    max_seg: float = 3.2,
) -> List[Tuple[float, float]]:
    """배경 컷 블록 [ (start,end), ... ] 을 계산합니다(순수 함수).

    자막 시작점을 컷 지점으로 삼되(말과 화면이 같이 바뀜):
      - 너무 짧은 블록은 앞 블록에 병합(min_seg)
      - 너무 긴 블록은 균등 분할(max_seg)
    자막이 없으면 max_seg 간격으로 균등 분할합니다.
    """
    total = max(0.0, float(total))
    if total <= 0:
        return []

    # 컷 지점 수집
    cuts = [0.0]
    for c in captions:
        if 0 < c.start < total:
            cuts.append(float(c.start))
    cuts.append(total)
    cuts = sorted(set(round(x, 3) for x in cuts))

    # 최소 길이 병합
    merged = [cuts[0]]
    for t in cuts[1:]:
        if t - merged[-1] < min_seg and t != total:
            continue
        merged.append(t)
    if merged[-1] != total:
        merged[-1] = total

    # 블록화 + 최대 길이 분할
    blocks: List[Tuple[float, float]] = []
    for i in range(len(merged) - 1):
        a, b = merged[i], merged[i + 1]
        span = b - a
        if span <= 0:
            continue
        n = max(1, int(span // max_seg) + (1 if span % max_seg > 0.4 else 0))
        step = span / n
        for k in range(n):
            s = a + k * step
            e = b if k == n - 1 else a + (k + 1) * step
            blocks.append((round(s, 3), round(e, 3)))
    return blocks


# --- ASS 자막 생성(순수 함수) ------------------------------------------------

def _ass_color(hex_color: str) -> str:
    """#RRGGBB → ASS &HAABBGGRR (알파 00=불투명)."""
    c = hex_color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        c = "FFFFFF"
    r, g, b = c[0:2], c[2:4], c[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    text = text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
    return text.replace("\n", "\\N")


def build_ass(captions: Sequence[Caption], style: RenderStyle) -> str:
    """자막 세그먼트 → ASS 자막 파일 텍스트(굵은 한글, 외곽선/그림자)."""
    primary = _ass_color(style.primary)
    outline = _ass_color(style.outline)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {style.width}
PlayResY: {style.height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{style.font},{style.font_size},{primary},{primary},{outline},&H80000000,-1,0,0,0,100,100,0,0,1,{style.outline_w},{style.shadow},2,80,80,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for c in captions:
        if not c.text.strip():
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},Cap,,0,0,0,,"
            f"{_ass_escape(c.text.strip())}"
        )
    return "\n".join(lines) + "\n"


# --- 렌더 --------------------------------------------------------------------

@dataclass
class RenderResult:
    video_path: str
    duration: float
    num_blocks: int
    warnings: List[str] = field(default_factory=list)


def _cover_filter(style: RenderStyle) -> str:
    """소재를 세로 프레임에 꽉 차게 cover-crop 하는 필터."""
    w, h = style.width, style.height
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1,fps={style.fps},format=yuv420p"
    )


def _render_block(
    src: str, dur: float, out: str, style: RenderStyle, seek: float, warnings: List[str]
) -> None:
    """한 블록을 정규화된 무음 클립으로 렌더."""
    exe = ffmpeg_exe()
    w, h = style.width, style.height
    if is_image(src):
        if style.ken_burns:
            frames = max(1, int(round(dur * style.fps)))
            # 살짝만 크게(1.25x) cover-crop 후 타깃 크기로 천천히 줌인.
            # (거대한 캔버스 zoompan 은 매우 느리므로 슈퍼샘플을 절제)
            sw, sh = int(w * 1.25), int(h * 1.25)
            vf = (
                f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
                f"zoompan=z='min(zoom+0.0009,1.15)':d={frames}:s={w}x{h}:fps={style.fps},"
                f"setsar=1,format=yuv420p"
            )
        else:
            vf = _cover_filter(style)
        cmd = [exe, "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", src,
               "-vf", vf, "-r", str(style.fps), "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out]
    else:
        # 영상: 소스가 짧으면 루프. seek 로 매번 다른 구간 노출.
        cmd = [exe, "-y", "-stream_loop", "-1", "-ss", f"{seek:.3f}", "-t", f"{dur:.3f}",
               "-i", src, "-vf", _cover_filter(style), "-r", str(style.fps), "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out]
    _run(cmd)


def render_short(
    narration_audio: str,
    footage: Sequence[str],
    captions: Sequence[Caption],
    out_path: str,
    *,
    style: Optional[RenderStyle] = None,
    clip_order: str = "sequential",
    clip_seed: int = 0,
    duration: Optional[float] = None,
) -> RenderResult:
    """세로 쇼츠 mp4 를 렌더합니다.

    Args:
        narration_audio: 나레이션 음성(길이가 영상 길이를 결정).
        footage: 내 소재 파일 목록(영상/이미지). 컷마다 순환 배치.
        captions: 구워 넣을 자막 세그먼트.
        out_path: 출력 mp4 경로.
        duration: 강제 길이(초). 미지정 시 나레이션 길이 사용.
    """
    from capcut_agent.draft_builder import assign_clips  # 컷↔클립 배치 재사용

    style = style or RenderStyle()
    warnings: List[str] = []
    footage = [f for f in footage if os.path.isfile(f)]
    if not footage:
        raise ValueError("사용 가능한 소재가 없습니다.")

    total = duration if duration is not None else media_duration(narration_audio)
    if not total or total <= 0:
        raise ValueError("나레이션 길이를 확인할 수 없습니다. --duration 으로 지정하세요.")

    blocks = plan_blocks(captions, total)
    if not blocks:
        blocks = [(0.0, total)]
    assignment = assign_clips(len(blocks), len(footage), clip_order, clip_seed)
    seeks = [0.0] * len(footage)

    tmpdir = tempfile.mkdtemp(prefix="shorts_render_")
    seg_files: List[str] = []
    try:
        for i, (a, b) in enumerate(blocks):
            dur = max(0.2, b - a)
            src = footage[assignment[i]]
            seg = os.path.join(tmpdir, f"seg_{i:04d}.mp4")
            _render_block(src, dur, seg, style, seeks[assignment[i]], warnings)
            seeks[assignment[i]] += dur  # 같은 영상 재사용 시 다른 구간
            seg_files.append(seg)

        # 배경 concat (동일 코덱 → copy)
        listfile = os.path.join(tmpdir, "list.txt")
        with open(listfile, "w", encoding="utf-8") as f:
            for s in seg_files:
                f.write(f"file '{s}'\n")
        bg = os.path.join(tmpdir, "bg.mp4")
        _run([ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", listfile,
              "-c", "copy", bg])

        # 자막(ASS) + 나레이션 합성 → 최종 출력
        assfile = os.path.join(tmpdir, "subs.ass")
        with open(assfile, "w", encoding="utf-8") as f:
            f.write(build_ass(captions, style))

        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        ass_arg = assfile.replace("\\", "/").replace(":", "\\:")
        _run([
            ffmpeg_exe(), "-y", "-i", bg, "-i", narration_audio,
            "-vf", f"subtitles={ass_arg}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", out_path,
        ])
    finally:
        # 임시 세그먼트 정리(출력은 out_path 로 이미 복사됨)
        for s in seg_files:
            try:
                os.remove(s)
            except OSError:
                pass

    return RenderResult(
        video_path=out_path,
        duration=round(total, 2),
        num_blocks=len(blocks),
        warnings=warnings,
    )


def captions_from_segments(segments) -> List[Caption]:
    """capcut_agent.lyrics.LyricSegment 등 (start,end,text) → Caption 목록."""
    out: List[Caption] = []
    for s in segments:
        out.append(Caption(start=float(s.start), end=float(s.end), text=s.text))
    return out
