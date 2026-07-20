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
        if not args.audio:
            raise SystemExit("--config 없이 실행하려면 최소한 --audio 가 필요합니다.")
        if not (args.background or args.background_dir):
            raise SystemExit("배경 소재가 필요합니다: --background <파일...> 또는 --background-dir <폴더>")
        data = {"audio_path": args.audio}
        if args.draft_folder:
            data["draft_folder"] = args.draft_folder
        if args.background:
            data["background_paths"] = list(args.background)
        if args.background_dir:
            data["background_dir"] = args.background_dir
        config = from_dict(data)

    # CLI 배경 인자가 있으면 설정 파일 값을 덮어씀.
    if args.background:
        config.background_paths = list(args.background)
        config.background_path = None
    if args.background_dir:
        config.background_dir = args.background_dir

    # 그 외 스칼라 오버라이드.
    overrides = {
        "draft_name": args.name,
        "draft_folder": args.draft_folder,
        "style": args.style,
        "clip_order": args.clip_order,
        "songbook": args.songbook,
        "song": args.song,
        "lyrics_file": args.lyrics_file,
        "keep_adlibs": args.keep_adlibs,
        "language": args.language,
        "whisper_model": args.whisper_model,
        "lyrics_srt": args.lyrics_srt,
        "output_srt": args.output_srt,
    }
    for key, val in overrides.items():
        if val is not None:
            setattr(config, key, val)

    # 초안 폴더 미지정 시 OS 표준 위치에서 자동 감지.
    if not config.draft_folder:
        from .capcut_paths import default_draft_folder

        detected = default_draft_folder()
        if detected:
            config.draft_folder = detected
            _log(f"[초안폴더] 자동 감지 → {detected}")

    # 스타일 유효성 조기 검증(지정된 경우만; None 이면 곡 무드로 자동 결정).
    if config.style is not None:
        get_preset(config.style)
    return config


def _resolve_official_lines(config: AgentConfig):
    """정답 가사 줄과(있으면) 곡 정보를 돌려줍니다. 없으면 (None, None)."""
    from .songbook import clean_lyric_lines, find_song, load_songbook

    # 1) 직접 입력한 가사 텍스트
    raw = None
    if config.lyrics_text:
        raw = config.lyrics_text
    elif config.lyrics_file:
        with open(config.lyrics_file, "r", encoding="utf-8") as f:
            raw = f.read()
    if raw:
        return clean_lyric_lines(raw, keep_adlibs=config.keep_adlibs), None

    # 2) 송북(엑셀) + 곡명
    if config.songbook and config.song:
        songs = load_songbook(config.songbook)
        song = find_song(songs, config.song)
        if song is None:
            raise ValueError(
                f"송북에서 곡 '{config.song}' 을 찾지 못했습니다. (총 {len(songs)}곡)"
            )
        return song.lyric_lines(keep_adlibs=config.keep_adlibs), song
    return None, None


def _get_lyrics(config: AgentConfig, beatmap, official) -> list:
    from .lyrics import clamp_segments_to_duration, correct_lyrics, transcribe

    if official:
        # 정답 가사 + Whisper 타이밍 = 강제 정렬(교정).
        _log(f"[가사] 정답 가사 {len(official)}줄 → Whisper({config.whisper_model}) 타이밍에 정렬(교정) 중…")
        segments = correct_lyrics(
            config.audio_path,
            official,
            model_size=config.whisper_model,
            language=config.language,
            duration=beatmap.duration,
        )
    elif config.lyrics_srt:
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

    # 정답 가사 + 곡 정보(있으면). 무드로 스타일 자동 선택.
    official, song = _resolve_official_lines(config)
    if song is not None:
        _log(f"[곡] {song.title} · 무드 '{song.mood}'"
             + (f" · 길이 {song.duration:.0f}s" if song.duration else ""))
        guide = song.background_guide()
        if guide:
            _log(f"     배경 가이드: {guide.get('video', '')} / 색감 {guide.get('color', '')}")
        if config.style is None:
            config.style = song.style()
            _log(f"     무드 기반 스타일 자동 선택 → {config.style}")

    from .audio import analyze_audio
    from .draft_builder import plan_summary

    _log(f"[오디오] 분석 중: {config.audio_path}")
    beatmap = analyze_audio(config.audio_path)
    _log(f"[오디오] {beatmap.duration:.1f}s · ~{beatmap.tempo:.0f} BPM · 비트 {len(beatmap.beats)}개")

    lyrics = _get_lyrics(config, beatmap, official)

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


def cmd_detect(args: argparse.Namespace) -> int:
    from .capcut_paths import candidate_draft_folders, find_draft_folders

    found = find_draft_folders()
    if found:
        print("발견된 캡컷 초안 폴더:")
        for p in found:
            print(f"  ✓ {p}")
        print("\n--draft-folder 를 생략하면 위 첫 번째 폴더가 자동 사용됩니다.")
    else:
        print("표준 위치에서 캡컷 초안 폴더를 찾지 못했습니다. 확인한 후보 경로:")
        for p in candidate_draft_folders():
            print(f"  · {p}")
        print("\n캡컷을 한 번 실행해 초안을 만든 뒤 다시 시도하거나, --draft-folder 로 직접 지정하세요.")
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
    run.add_argument(
        "--background",
        nargs="+",
        help="배경 영상/이미지 파일(여러 개 지정 가능). 비트에 맞춰 순환 배치됨",
    )
    run.add_argument("--background-dir", dest="background_dir", help="배경 클립들이 담긴 폴더")
    run.add_argument(
        "--clip-order",
        dest="clip_order",
        choices=["sequential", "shuffle"],
        help="클립 배치 순서 (sequential=순환, shuffle=무작위)",
    )
    run.add_argument("--draft-folder", dest="draft_folder", help="캡컷 초안 루트 폴더(생략 시 자동 감지)")
    run.add_argument("--name", help="초안(프로젝트) 이름")
    run.add_argument("--style", help=f"스타일 프리셋 ({', '.join(list_presets())})")
    run.add_argument("--songbook", help="곡별 정답 가사 엑셀(Mindtrack 형식)")
    run.add_argument("--song", help="송북 안에서 사용할 곡명(정답 가사·무드 가져옴)")
    run.add_argument("--lyrics-file", dest="lyrics_file", help="정답 가사 텍스트 파일")
    run.add_argument(
        "--no-adlibs",
        dest="keep_adlibs",
        action="store_false",
        default=None,
        help="괄호 애드립/백보컬 줄을 자막에서 제외",
    )
    run.add_argument("--language", help="Whisper 언어 코드(ko/en/…), 미지정 시 자동")
    run.add_argument("--whisper-model", dest="whisper_model", help="Whisper 모델 크기")
    run.add_argument("--lyrics-srt", dest="lyrics_srt", help="준비된 SRT 사용(받아쓰기 생략)")
    run.add_argument("--output-srt", dest="output_srt", help="받아쓴 가사 SRT 저장 경로")
    run.add_argument("--dry-run", action="store_true", help="초안 생성 없이 계획만 출력")
    run.set_defaults(func=cmd_run)

    styles = sub.add_parser("styles", help="사용 가능한 스타일 목록")
    styles.set_defaults(func=cmd_styles)

    detect = sub.add_parser("detect", help="캡컷 초안 폴더 자동 감지 결과 출력")
    detect.set_defaults(func=cmd_detect)

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
