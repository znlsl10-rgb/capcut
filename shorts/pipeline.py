"""쇼츠 파이프라인 — 나레이션 + 내 소재 + 대본 → 세로 캡컷 초안 + 메타데이터.

기존 `capcut_agent` 엔진을 그대로 재사용합니다. 대본 자막 라인을 나레이션 음성에
**강제정렬**해 타이밍을 얻고, 내 소재를 문장 전환에 맞춰 컷 편집합니다.

무거운 의존성(librosa/whisper/pyCapCut)은 실제 초안 생성 시에만 지연 임포트됩니다.
`plan_short()` 은 라이브러리 없이 계획/메타데이터만 미리 보여줍니다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .channel import ChannelProfile
from .metadata import PublishMetadata, build_metadata
from .script import MotivationScript


@dataclass
class ShortResult:
    """쇼츠 산출물 경로 모음."""

    srt_path: str
    metadata_path: str
    manifest_path: str
    video_path: Optional[str] = None   # 렌더한 완성 mp4(헤드리스 경로)
    draft_path: Optional[str] = None   # 캡컷 초안(선택)
    warnings: List[str] = field(default_factory=list)


def plan_short(
    script: MotivationScript,
    channel: ChannelProfile,
    *,
    max_caption_chars: int = 16,
) -> str:
    """라이브러리 없이 쇼츠 편집 계획을 텍스트로 요약(미리보기)."""
    from .script import estimate_seconds

    captions = script.caption_lines(max_chars=max_caption_chars)
    est = estimate_seconds(script.narration_text())
    yt = build_metadata(script, channel, platform="youtube")

    lines = [
        f"🎯 주제: {script.topic or '(미지정)'}",
        f"📺 채널: {channel.name} · 니치 '{channel.niche}' · 톤 '{channel.tone}'",
        f"🎬 스타일 프리셋: {channel.resolved_style()}",
        f"⏱  예상 길이: 약 {est:.0f}s (나레이션 낭독 기준)",
        f"🪝 훅: {script.hook()}",
        f"📝 자막 라인: {len(captions)}개 (최대 {max_caption_chars}자/줄)",
        f"📣 CTA: {script.cta() or channel.cta}",
        "",
        f"▶ 제목: {yt.title}",
        f"▶ 해시태그: {' '.join(yt.hashtags)}",
    ]
    return "\n".join(lines)


def build_short(
    script: MotivationScript,
    channel: ChannelProfile,
    *,
    narration_audio: str,
    footage: List[str],
    draft_folder: Optional[str] = None,
    draft_name: str = "motiv_short",
    output_dir: Optional[str] = None,
    max_caption_chars: int = 16,
    whisper_model: str = "small",
    clip_order: str = "sequential",
    render: bool = True,
    make_draft: bool = False,
    align: bool = True,
    dry_run: bool = False,
) -> ShortResult:
    """세로 쇼츠를 생성합니다(헤드리스 mp4 렌더 + 메타/자막/게시 매니페스트).

    두 경로를 독립적으로 켤 수 있습니다:
      - render=True     : ffmpeg 로 완성 mp4 직접 렌더(캡컷 없이 무인). 기본 ON.
      - make_draft=True : 캡컷 초안(손보기용)도 함께 생성. pyCapCut 필요.

    자막 타이밍:
      - align=True 면 Whisper 강제정렬(정확). 불가하면 나레이션 길이에 비례 분배로 폴백.

    Args:
        narration_audio: 나레이션 음성 파일(내 목소리 또는 TTS).
        footage: 내 소재(영상/이미지) 파일 목록.
        output_dir: 메타/자막/매니페스트/mp4 저장 폴더(기본: 현재 폴더).
        dry_run: True 면 렌더/초안 없이 메타데이터 + 미리보기 자막만 씁니다.
    """
    output_dir = output_dir or "."
    os.makedirs(output_dir, exist_ok=True)
    warnings: List[str] = []

    # 게시 메타데이터(유튜브/틱톡) — 라이브러리 불필요, 항상 먼저 씀.
    meta = build_metadata(script, channel, platform="youtube")
    metadata_path = os.path.join(output_dir, f"{draft_name}.metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "youtube": meta.to_dict(),
                "tiktok": build_metadata(script, channel, platform="tiktok").to_dict(),
                "topic": script.topic,
                "hook": script.hook(),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    srt_path = os.path.join(output_dir, f"{draft_name}.srt")
    caption_lines = script.caption_lines(max_chars=max_caption_chars)

    from capcut_agent.lyrics import write_srt

    # --- 자막 타이밍 세그먼트 결정 ---------------------------------------
    if dry_run:
        segments = _even_segments(caption_lines)
    else:
        segments = _timed_segments(
            caption_lines, narration_audio, align=align,
            language=channel.language, whisper_model=whisper_model, warnings=warnings,
        )
    write_srt(segments, srt_path)

    video_path: Optional[str] = None
    draft_path: Optional[str] = None

    # --- 헤드리스 mp4 렌더(기본 경로) ------------------------------------
    if render and not dry_run:
        from .render import RenderStyle, captions_from_segments, render_short
        from capcut_agent.transitions import get_preset

        preset = get_preset(channel.resolved_style())
        style = RenderStyle(
            font_size=int(round(preset.text_size * 9)),
            primary=preset.text_color,
        )
        video_path = os.path.join(output_dir, f"{draft_name}.mp4")
        res = render_short(
            narration_audio, footage, captions_from_segments(segments), video_path,
            style=style, clip_order=clip_order,
        )
        warnings.extend(res.warnings)

    # --- 캡컷 초안(선택) --------------------------------------------------
    if make_draft and not dry_run:
        draft_path = _build_capcut_draft(
            script, channel, narration_audio, footage, segments,
            draft_folder, draft_name, whisper_model, clip_order, warnings,
        )

    # --- 게시 매니페스트 --------------------------------------------------
    manifest_path = os.path.join(output_dir, f"{draft_name}.publish.json")
    from .publish import write_publish_manifest

    write_publish_manifest(
        manifest_path,
        channel=channel,
        script=script,
        draft_path=draft_path or "",
        srt_path=srt_path,
        video_path=video_path,
    )

    return ShortResult(
        srt_path=srt_path,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        video_path=video_path,
        draft_path=draft_path,
        warnings=warnings,
    )


def _timed_segments(caption_lines, narration_audio, *, align, language, whisper_model, warnings):
    """자막 라인에 타이밍을 부여. align=True 면 Whisper 강제정렬, 실패 시 길이 비례 분배."""
    from .render import media_duration

    total = media_duration(narration_audio) or 0.0
    if align:
        try:
            from capcut_agent.audio import analyze_audio
            from capcut_agent.lyrics import clamp_segments_to_duration, correct_lyrics

            beatmap = analyze_audio(narration_audio)
            segs = correct_lyrics(narration_audio, caption_lines,
                                  model_size=whisper_model, language=language,
                                  duration=beatmap.duration)
            return clamp_segments_to_duration(segs, beatmap.duration)
        except Exception as exc:  # noqa: BLE001  (Whisper/librosa 미설치 등)
            warnings.append(f"[info] 강제정렬 불가 → 길이 비례 자막 분배로 진행 ({exc})")
    if total <= 0:
        return _even_segments(caption_lines)
    return _distribute(caption_lines, total)


def _distribute(caption_lines: List[str], total: float, *, min_dur: float = 0.6):
    """자막 라인을 [0,total] 에 글자 수 비례로 분배(총길이를 절대 넘지 않음)."""
    from capcut_agent.lyrics import LyricSegment

    lines = [t for t in caption_lines if t.strip()]
    if not lines:
        return []
    weights = [max(1, len(t.replace(" ", ""))) for t in lines]
    wsum = sum(weights) or 1
    # 최소 길이를 다 주면 총길이를 넘는 경우엔 최소 길이를 포기하고 순수 비례.
    use_min = total >= min_dur * len(lines)

    segs: List = []
    t = 0.0
    for i, (text, w) in enumerate(zip(lines, weights)):
        dur = total * w / wsum
        if use_min:
            dur = max(min_dur, dur)
        start = min(t, total)
        end = total if i == len(lines) - 1 else min(total, start + dur)
        if end < start:
            end = start
        segs.append(LyricSegment(start=round(start, 3), end=round(end, 3), text=text))
        t = end
    return segs


def _build_capcut_draft(script, channel, narration_audio, footage, segments,
                        draft_folder, draft_name, whisper_model, clip_order, warnings):
    """캡컷 초안(손보기용) 생성. pyCapCut 필요."""
    from capcut_agent.audio import analyze_audio
    from capcut_agent.config import from_dict
    from capcut_agent.draft_builder import build_draft

    cfg_data = {
        "audio_path": narration_audio,
        "background_paths": list(footage),
        "draft_name": draft_name,
        "style": channel.resolved_style(),
        "language": channel.language,
        "whisper_model": whisper_model,
        "clip_order": clip_order,
        "emphasize_lyrics": True,
        "width": 1080,
        "height": 1920,
    }
    if draft_folder:
        cfg_data["draft_folder"] = draft_folder
    config = from_dict(cfg_data)
    if not config.draft_folder:
        from capcut_agent.capcut_paths import default_draft_folder

        detected = default_draft_folder()
        if detected:
            config.draft_folder = detected
    config.validate_paths()
    beatmap = analyze_audio(config.audio_path)
    path, w = build_draft(config, beatmap, segments)
    warnings.extend(w)
    return path


def _even_segments(caption_lines: List[str], per_line: float = 2.0):
    """미리보기용: 각 자막을 per_line 초씩 균등 배치한 세그먼트."""
    from capcut_agent.lyrics import LyricSegment

    segs = []
    t = 0.0
    for text in caption_lines:
        segs.append(LyricSegment(start=t, end=t + per_line, text=text))
        t += per_line
    return segs
