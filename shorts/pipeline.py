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

    draft_path: str
    srt_path: str
    metadata_path: str
    manifest_path: str
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
    dry_run: bool = False,
) -> ShortResult:
    """세로 쇼츠 캡컷 초안을 생성하고, 메타데이터/매니페스트를 함께 씁니다.

    Args:
        narration_audio: 나레이션 음성 파일(내 목소리 또는 TTS).
        footage: 내 소재(영상/이미지) 파일 목록.
        draft_folder: 캡컷 초안 루트 폴더(생략 시 자동 감지).
        output_dir: 메타/자막/매니페스트를 저장할 폴더(기본: 현재 폴더).
        dry_run: True 면 초안 생성은 건너뛰고 메타데이터/자막만 씁니다.
    """
    output_dir = output_dir or "."
    os.makedirs(output_dir, exist_ok=True)

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

    warnings: List[str] = []
    srt_path = os.path.join(output_dir, f"{draft_name}.srt")
    captions = script.caption_lines(max_chars=max_caption_chars)

    if dry_run:
        # 소재/캡컷 폴더 없이 미리보기: 균등 타이밍 임시 SRT + 초안 경로는 예정값.
        from capcut_agent.lyrics import write_srt

        write_srt(_even_segments(captions), srt_path)
        draft_path = os.path.join(draft_folder or output_dir, draft_name)
    else:
        # 실제 생성 — 여기서만 무거운 의존성/설정을 사용.
        from capcut_agent.config import from_dict

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
        from capcut_agent.audio import analyze_audio
        from capcut_agent.draft_builder import build_draft
        from capcut_agent.lyrics import clamp_segments_to_duration, correct_lyrics, write_srt

        beatmap = analyze_audio(config.audio_path)
        segments = correct_lyrics(
            config.audio_path,
            captions,
            model_size=config.whisper_model,
            language=config.language,
            duration=beatmap.duration,
        )
        segments = clamp_segments_to_duration(segments, beatmap.duration)
        write_srt(segments, srt_path)

        draft_path, warnings = build_draft(config, beatmap, segments)

    manifest_path = os.path.join(output_dir, f"{draft_name}.publish.json")
    from .publish import write_publish_manifest

    write_publish_manifest(
        manifest_path,
        channel=channel,
        script=script,
        draft_path=draft_path,
        srt_path=srt_path,
        video_path=None,  # 캡컷에서 내보낸 mp4 경로를 나중에 채움
    )

    return ShortResult(
        draft_path=draft_path,
        srt_path=srt_path,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        warnings=warnings,
    )


def _even_segments(captions: List[str], per_line: float = 2.0):
    """미리보기용: 각 자막을 per_line 초씩 균등 배치한 세그먼트."""
    from capcut_agent.lyrics import LyricSegment

    segs = []
    t = 0.0
    for text in captions:
        segs.append(LyricSegment(start=t, end=t + per_line, text=text))
        t += per_line
    return segs
