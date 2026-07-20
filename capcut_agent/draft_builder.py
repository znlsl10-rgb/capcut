"""캡컷(CapCut / 剪映) 초안 빌더.

분석 결과(BeatMap) + 가사(LyricSegment) + 스타일 프리셋을 받아
pyJianYingDraft 로 실제 초안 프로젝트를 생성합니다.

트랙 구성(아래→위):
    1) 배경 영상 트랙  : 비트 지점에서 컷 + 전환 + 줌 애니 (소름돋는 화면 전환)
    2) 노래 오디오 트랙
    3) 가사 자막 트랙  : Whisper 타임스탬프 + 입장 애니

`plan_summary()` 는 라이브러리 없이 편집 계획을 텍스트로 요약합니다(미리보기용).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .audio import BeatMap, TransitionPoint, segment_boundaries, select_transition_points
from .config import AgentConfig
from .lyrics import LyricSegment, clamp_segments_to_duration
from .transitions import StylePreset, get_preset

SEC_US = 1_000_000


def _us(seconds: float) -> int:
    """초 → 마이크로초(정수)."""
    return int(round(max(0.0, seconds) * SEC_US))


def _hex_to_rgb(color: str) -> Tuple[float, float, float]:
    """'#RRGGBB' → (r,g,b) 0~1 튜플."""
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return (1.0, 1.0, 1.0)
    r, g, b = (int(c[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b)


def _plan_points(
    config: AgentConfig,
    beatmap: BeatMap,
    lyric_segments: Sequence[LyricSegment] = (),
) -> List[TransitionPoint]:
    windows: List[Tuple[float, float]] = []
    if config.emphasize_lyrics and lyric_segments:
        windows = [(s.start, s.end) for s in lyric_segments]
    return select_transition_points(
        beatmap,
        min_gap=config.min_transition_gap,
        subdivision=config.beat_subdivision,
        max_count=config.max_transitions,
        emphasis_windows=windows,
    )


def assign_clips(
    num_segments: int,
    num_clips: int,
    order: str = "sequential",
    seed: int = 0,
) -> List[int]:
    """각 배경 컷(세그먼트)에 사용할 클립 인덱스를 정합니다 (순수 함수).

    - "sequential": 0,1,2,...,0,1,2,... 순환. 컷마다 다음 클립이 나와
      비트에 맞춰 화면이 계속 바뀌는 몽타주가 됩니다.
    - "shuffle": 무작위이되 같은 클립이 연속되지 않도록 하고, 모든 클립을
      한 바퀴 다 쓴 뒤 다시 섞습니다(균등 사용).

    Args:
        num_segments: 배경 컷 개수.
        num_clips: 사용할 클립 개수.
        order: "sequential" 또는 "shuffle".
        seed: shuffle 재현용 시드.

    Returns:
        길이 num_segments 인 클립 인덱스 리스트.
    """
    if num_clips <= 0 or num_segments <= 0:
        return []
    if num_clips == 1:
        return [0] * num_segments
    if order == "shuffle":
        import random

        rnd = random.Random(seed)
        result: List[int] = []
        bag: List[int] = []
        prev = -1
        for _ in range(num_segments):
            if not bag:
                bag = list(range(num_clips))
                rnd.shuffle(bag)
                if bag[0] == prev:  # 바구니 경계에서 연속 방지
                    bag.append(bag.pop(0))
            choice = bag.pop(0)
            result.append(choice)
            prev = choice
        return result
    # sequential
    return [i % num_clips for i in range(num_segments)]


def plan_summary(
    config: AgentConfig,
    beatmap: BeatMap,
    lyric_segments: Sequence[LyricSegment],
    *,
    preset: Optional[StylePreset] = None,
) -> str:
    """편집 계획 요약(사람이 읽는 텍스트). 라이브러리 불필요."""
    preset = preset or get_preset(config.style)
    lyrics = clamp_segments_to_duration(lyric_segments, beatmap.duration)
    points = _plan_points(config, beatmap, lyrics)
    strong = sum(1 for p in points if p.strong)
    clips = config.resolved_backgrounds()

    lines = [
        f"🎬 편집 계획 — 프리셋 '{preset.name}' ({preset.description})",
        f"   길이 {beatmap.duration:.1f}s · 템포 ~{beatmap.tempo:.0f} BPM",
        f"   배경 클립 {len(clips)}개 · 배치 '{config.clip_order}'",
        f"   화면 전환 {len(points)}회 (강렬/드롭 {strong}회), 배경 컷 {len(points) + 1}개",
        f"   가사 자막 {len(lyrics)}줄"
        + ("  · 가사 구간 박자 강조 ON" if config.emphasize_lyrics else ""),
        f"   일반 전환: {', '.join(preset.transitions)}",
        f"   드롭 전환: {', '.join(preset.strong_transitions)}",
    ]
    return "\n".join(lines)


def _source_window(Timerange, material, seg_dur_us: int, cursor_us: int, is_photo: bool):
    """배경 소재에서 잘라 쓸 구간을 계산합니다(영상은 순환, 이미지는 고정)."""
    mat_dur = int(getattr(material, "duration", 0) or 0)
    if is_photo or mat_dur <= 0:
        return Timerange(0, seg_dur_us)
    if seg_dur_us >= mat_dur:
        # 세그먼트가 소재보다 길면 전체를 느리게 재생(슬로모).
        return Timerange(0, mat_dur)
    start = cursor_us % mat_dur
    if start + seg_dur_us > mat_dur:
        start = mat_dur - seg_dur_us
    return Timerange(start, seg_dur_us)


def _resolve(enum_cls, name: str, warnings: List[str]):
    """enum 멤버명을 실제 멤버로 해석. 없으면 None + 경고 기록."""
    member = getattr(enum_cls, name, None)
    if member is None:
        warnings.append(f"'{name}' 효과를 {enum_cls.__name__} 에서 찾지 못해 건너뜀")
    return member


def build_draft(
    config: AgentConfig,
    beatmap: BeatMap,
    lyric_segments: Sequence[LyricSegment],
    *,
    preset: Optional[StylePreset] = None,
) -> Tuple[str, List[str]]:
    """캡컷 초안을 생성하고 저장합니다.

    Returns:
        (draft_path, warnings) — 생성된 초안 폴더 경로와 비치명적 경고 목록.
    """
    import os

    import pyJianYingDraft as draft
    from pyJianYingDraft import (
        AudioMaterial,
        AudioSegment,
        ClipSettings,
        DraftFolder,
        IntroType,
        TextIntro,
        TextSegment,
        TextStyle,
        Timerange,
        TrackSpec,
        TrackType,
        TransitionType,
        VideoMaterial,
        VideoSceneEffectType,
        VideoSegment,
    )

    preset = preset or get_preset(config.style)
    warnings: List[str] = []

    folder = DraftFolder(config.draft_folder)
    script = folder.create_draft(
        config.draft_name, config.width, config.height, fps=config.fps, allow_replace=True
    )

    # 트랙 생성 (아래→위 순서로 쌓임)
    script.append_track(TrackSpec(TrackType.video, "background"))
    script.append_track(TrackSpec(TrackType.audio, "song"))
    script.append_track(TrackSpec(TrackType.text, "lyrics"))

    # --- 배경 트랙: 여러 클립을 비트에 맞춰 컷 + 전환 + 줌 애니 -----------
    lyrics_for_plan = clamp_segments_to_duration(lyric_segments, beatmap.duration)
    points = _plan_points(config, beatmap, lyrics_for_plan)
    bounds = segment_boundaries(points, beatmap.duration)
    strong_at = {round(p.time, 3): p.strong for p in points}

    # 배경 클립 소재 로드(읽기 실패한 파일은 경고 후 제외).
    materials: List = []
    is_photo: List[bool] = []
    for path in config.resolved_backgrounds():
        try:
            mat = VideoMaterial(path)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"배경 클립 로드 실패, 건너뜀: {path} ({exc})")
            continue
        materials.append(mat)
        is_photo.append(getattr(mat, "material_type", "video") == "photo")
    if not materials:
        raise ValueError("사용 가능한 배경 클립이 없습니다.")

    num_segments = len(bounds) - 1
    assignment = assign_clips(num_segments, len(materials), config.clip_order, config.clip_seed)
    cursors = [0] * len(materials)  # 클립별 재생 헤드(연속 사용 시 다른 부분 노출)

    for idx in range(num_segments):
        start_s, end_s = bounds[idx], bounds[idx + 1]
        seg_dur_us = _us(end_s - start_s)
        if seg_dur_us <= 0:
            continue

        clip_idx = assignment[idx]
        mat = materials[clip_idx]
        target = Timerange(_us(start_s), seg_dur_us)
        source = _source_window(Timerange, mat, seg_dur_us, cursors[clip_idx], is_photo[clip_idx])
        cursors[clip_idx] += seg_dur_us  # 다음에 이 클립을 쓰면 이어지는 부분 사용
        seg = VideoSegment(mat, target, source_timerange=source)

        # 세로/가로 비율이 다를 때 배경을 블러로 채워 빈 곳을 없앰.
        try:
            seg.add_background_filling("blur", 0.0625)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"배경 블러 적용 실패: {exc}")

        # 입장 애니메이션(줌 펀치). 세그먼트 시작 지점의 강박 여부 사용.
        intro_strong = strong_at.get(round(start_s, 3), False)
        intro_name = preset.pick_bg_intro(intro_strong)
        if intro_name:
            member = _resolve(IntroType, intro_name, warnings)
            if member is not None:
                seg.add_animation(member)

        # 다음 세그먼트로의 전환 (마지막 세그먼트 제외). 컷 지점 = 비트 시각이므로
        # 전환은 박자에 정확히 맞습니다. 인접 두 컷 길이로 전환 길이를 제한.
        is_last = idx == num_segments - 1
        if not is_last:
            boundary_time = round(end_s, 3)
            t_strong = strong_at.get(boundary_time, False)
            t_name = preset.pick_transition(idx, t_strong)
            if t_name:
                member = _resolve(TransitionType, t_name, warnings)
                if member is not None:
                    next_dur = bounds[idx + 2] - bounds[idx + 1]
                    cap = 0.9 * min(end_s - start_s, next_dur)
                    dur = min(preset.transition_duration_for(t_strong), cap)
                    if dur > 0.01:
                        seg.add_transition(member, duration=_us(dur))
            # 드롭/가사강조 구간엔 화면 효과(섬광 등)로 소름 포인트 강조.
            if t_strong and preset.scene_effect:
                member = _resolve(VideoSceneEffectType, preset.scene_effect, warnings)
                if member is not None:
                    try:
                        seg.add_effect(member)
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"화면 효과 적용 실패: {exc}")

        script.add_segment(seg, "background")

    # --- 오디오 트랙: 노래 원본 ------------------------------------------
    audio_mat = AudioMaterial(config.audio_path)
    song_us = min(_us(beatmap.duration), int(getattr(audio_mat, "duration", 0)) or _us(beatmap.duration))
    script.add_segment(AudioSegment(audio_mat, Timerange(0, song_us)), "song")

    # --- 자막 트랙: 가사 + 입장 애니 -------------------------------------
    text_style = TextStyle(
        size=preset.text_size,
        bold=True,
        color=_hex_to_rgb(preset.text_color),
        align=1,  # 가운데 정렬
        auto_wrapping=True,
    )
    clip = ClipSettings(transform_y=-0.72)  # 화면 하단쪽 배치

    lyrics = clamp_segments_to_duration(lyric_segments, beatmap.duration)
    for seg in lyrics:
        dur_us = _us(max(seg.end - seg.start, 0.2))
        tr = Timerange(_us(seg.start), dur_us)
        ts = TextSegment(seg.text, tr, style=text_style, clip_settings=clip)

        t_strong = _is_near_strong(seg.start, points)
        intro_name = preset.pick_text_intro(t_strong)
        member = _resolve(TextIntro, intro_name, warnings)
        if member is not None:
            try:
                ts.add_animation(member)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"자막 애니 적용 실패: {exc}")

        script.add_segment(ts, "lyrics")

    script.save()
    draft_path = os.path.join(config.draft_folder, config.draft_name)
    return draft_path, warnings


def _is_near_strong(time: float, points: Sequence[TransitionPoint], tol: float = 0.35) -> bool:
    """해당 시각 근처(tol 초)에 강박 전환이 있는지."""
    for p in points:
        if p.strong and abs(p.time - time) <= tol:
            return True
    return False
