"""CapCut Auto-Edit Agent CLI.

사용 예:
    # 설정 파일로 실행
    python -m capcut_agent run --config config.yaml

    # 인자로 바로 실행
    python -m capcut_agent run \\
        --audio song.mp3 --background bg.mp4 \\
        --draft-folder "~/Movies/CapCut/.../draft" \\
        --name my_video --style goosebump

    # 실제 초안을 만들지 않고 편집 계획만 미리보기 (오디오/가사만 분석)
    python -m capcut_agent run --config config.yaml --dry-run

    # 사용 가능한 스타일 목록
    python -m capcut_agent styles
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .config import AgentConfig, from_dict, load_config
from .transitions import get_preset, list_presets


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _build_config(args: argparse.Namespace) -> AgentConfig:
    if args.config:
        config = load_config(args.config)
    else:
        required = {"audio_path": args.audio, "background_path": args.background, "draft_folder": args.draft_folder}
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise SystemExit(
                "--config 없이 실행하려면 --audio, --background, --draft-folder 가 모두 필요합니다."
            )
        config = from_dict({k: v for k, v in required.items()})

    # CLI 인자가 있으면 설정 파일 값을 덮어씀.
    overrides = {
        "draft_name": args.name,
        "style": args.style,
        "language": args.language,
        "whisper_model": args.whisper_model,
        "lyrics_srt": args.lyrics_srt,
        "output_srt": args.output_srt,
    }
    for key, val in overrides.items():
        if val is not None:
            setattr(config, key, val)

    # 스타일 유효성 조기 검증(오타 즉시 알림).
    get_preset(config.style)
    return config


def _get_lyrics(config: AgentConfig, beatmap) -> list:
    from .lyrics import LyricSegment, clamp_segments_to_duration, transcribe

    if config.lyrics_srt:
        _log(f"[가사] SRT 파일 사용: {config.lyrics_srt}")
        segments = _parse_srt(config.lyrics_srt)
    else:
        _log(f"[가사] Whisper({config.whisper_model}) 받아쓰기 중… 시간이 걸릴 수 있어요.")
        segments = transcribe(
            config.audio_path, model_size=config.whisper_model, language=config.language
        )
    segments = clamp_segments_to_duration(segments, beatmap.duration)
    _log(f"[가사] {len(segments)}줄 확보")
    return segments


def _parse_srt(path: str) -> list:
    """간단한 SRT 파서 (외부 의존성 없음)."""
    from .lyrics import LyricSegment

    def _to_sec(ts: str) -> float:
        ts = ts.strip().replace(".", ",")
        hms, _, ms = ts.partition(",")
        h, m, s = (int(x) for x in hms.split(":"))
        return h * 3600 + m * 60 + s + (int(ms or 0) / 1000.0)

    out: List = []
    with open(path, "r", encoding="utf-8-sig") as f:
        blocks = f.read().strip().split("\n\n")
    for block in blocks:
        rows = [r for r in block.splitlines() if r.strip()]
        if len(rows) < 2:
            continue
        time_line = rows[1] if "-->" in rows[1] else rows[0]
        if "-->" not in time_line:
            continue
        start_s, _, end_s = time_line.partition("-->")
        text = "\n".join(rows[2:]) if "-->" in rows[1] else "\n".join(rows[1:])
        out.append(LyricSegment(start=_to_sec(start_s), end=_to_sec(end_s), text=text.strip()))
    return out


def cmd_run(args: argparse.Namespace) -> int:
    config = _build_config(args)
    config.validate_paths()

    from .audio import analyze_audio
    from .draft_builder import plan_summary

    _log(f"[오디오] 분석 중: {config.audio_path}")
    beatmap = analyze_audio(config.audio_path)
    _log(f"[오디오] {beatmap.duration:.1f}s · ~{beatmap.tempo:.0f} BPM · 비트 {len(beatmap.beats)}개")

    lyrics = _get_lyrics(config, beatmap)

    # 받아쓴 가사를 SRT 로 저장(재사용/수정 편의).
    if not config.lyrics_srt:
        from .lyrics import write_srt

        srt_path = config.resolved_output_srt()
        write_srt(lyrics, srt_path)
        _log(f"[가사] SRT 저장: {srt_path}")

    print(plan_summary(config, beatmap, lyrics))

    if args.dry_run:
        _log("\n[dry-run] 초안 생성은 건너뜁니다. --dry-run 을 빼면 실제 초안을 만듭니다.")
        return 0

    from .draft_builder import build_draft

    _log("\n[초안] 캡컷 프로젝트 생성 중…")
    draft_path, warnings = build_draft(config, beatmap, lyrics)
    for w in warnings:
        _log(f"  ⚠️  {w}")
    _log(f"[초안] 완료 → {draft_path}")
    _log("      캡컷을 열면 '초안' 목록에 프로젝트가 나타납니다. 확인 후 내보내기 하세요.")
    return 0


def cmd_styles(args: argparse.Namespace) -> int:
    print("사용 가능한 스타일 프리셋:\n")
    for name in list_presets():
        preset = get_preset(name)
        print(f"  • {name:<12} {preset.description}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="capcut_agent",
        description="노래에 맞춰 소름돋는 화면 전환 + 가사 자막을 자동 편집하는 캡컷 에이전트",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="편집 실행(초안 생성)")
    run.add_argument("--config", help="YAML 설정 파일 경로")
    run.add_argument("--audio", help="노래 오디오 파일")
    run.add_argument("--background", help="배경 영상/이미지 파일")
    run.add_argument("--draft-folder", dest="draft_folder", help="캡컷 초안 루트 폴더")
    run.add_argument("--name", help="초안(프로젝트) 이름")
    run.add_argument("--style", help=f"스타일 프리셋 ({', '.join(list_presets())})")
    run.add_argument("--language", help="Whisper 언어 코드(ko/en/…), 미지정 시 자동")
    run.add_argument("--whisper-model", dest="whisper_model", help="Whisper 모델 크기")
    run.add_argument("--lyrics-srt", dest="lyrics_srt", help="준비된 SRT 사용(받아쓰기 생략)")
    run.add_argument("--output-srt", dest="output_srt", help="받아쓴 가사 SRT 저장 경로")
    run.add_argument("--dry-run", action="store_true", help="초안 생성 없이 계획만 출력")
    run.set_defaults(func=cmd_run)

    styles = sub.add_parser("styles", help="사용 가능한 스타일 목록")
    styles.set_defaults(func=cmd_styles)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        _log(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
