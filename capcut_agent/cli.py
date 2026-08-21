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
        "footage_mode": args.footage_mode,
        "slow_floor": args.slow_floor,
        "songbook": args.songbook,
        "song": args.song,
        "lyrics_file": args.lyrics_file,
        "lyrics_ko_file": args.lyrics_ko_file,
        "translate": args.translate,
        "keep_adlibs": args.keep_adlibs,
        "language": args.language,
        "whisper_model": args.whisper_model,
        "lyrics_srt": args.lyrics_srt,
        "output_srt": args.output_srt,
        "script_file": getattr(args, "script", None),
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

    # 0) 대본(스크립트)이 있으면 그걸 자막으로 사용(비트에 맞춰 배치).
    if config.script_file:
        from .script_subs import script_to_segments

        with open(config.script_file, "r", encoding="utf-8") as f:
            text = f.read()
        segments = script_to_segments(text, beatmap.duration, beats=beatmap.beats)
        _log(f"[대본] {config.script_file} → 자막 {len(segments)}줄(비트에 맞춰 배치)")
        return clamp_segments_to_duration(segments, beatmap.duration)

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

    # 이중 자막: 한글 번역 붙이기 (파일 우선, 없으면 자동 번역 옵션)
    if config.lyrics_ko_file or config.translate:
        from .translate import build_secondary

        try:
            segments = build_secondary(
                segments,
                ko_file=config.lyrics_ko_file,
                auto_translate=config.translate,
                target=config.translate_target,
            )
            n_ko = sum(1 for s in segments if s.secondary)
            src = "파일" if config.lyrics_ko_file else "자동 번역"
            _log(f"[이중자막] 한글({src}) {n_ko}줄 부착 → 영어 위 / 한글 아래")
        except Exception as exc:  # noqa: BLE001
            _log(f"[이중자막] 한글 부착 실패(영어 단일로 진행): {exc}")

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
    return _execute_pipeline(config, dry_run=args.dry_run)


def _execute_pipeline(config: AgentConfig, *, dry_run: bool) -> int:
    """완성된 config 로 오디오 분석 → 가사 → 초안 생성까지 실행.

    cmd_run 과 cmd_benchmark 가 공유합니다.
    """
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

    if dry_run:
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


def cmd_analyze(args: argparse.Namespace) -> int:
    """참고 영상을 분석해 편집 레시피(프로파일)만 출력/저장합니다."""
    from .benchmark import analyze_reference, summarize_profile
    from .fetch import is_url, resolve_reference

    reference = args.reference
    if is_url(reference):
        _log(f"[벤치마크] 링크에서 참고 영상 다운로드 중: {reference}")
        reference = resolve_reference(reference, out_dir=".")
        _log(f"            → {reference}")

    _log(f"[벤치마크] 참고 영상 분석 중: {reference}")
    _log("            (장면컷 감지 + 오디오 템포 + 자막 밴드 추정 — 시간이 걸릴 수 있어요)")
    profile = analyze_reference(
        reference,
        detect_subs=not args.no_subtitles,
        measure_music=not args.no_music,
        scene_threshold=args.scene_threshold,
    )
    print(summarize_profile(profile))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(profile.to_json())
        _log(f"[벤치마크] 프로파일 JSON 저장 → {args.out}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    """참고 영상을 벤치마킹해 내 로컬 클립으로 유사한 영상 초안을 만듭니다."""
    import os

    from .benchmark import (
        analyze_reference,
        extract_reference_audio,
        profile_to_overrides,
        summarize_profile,
    )
    from .fetch import is_url, resolve_reference

    if not (args.background or args.background_dir):
        raise SystemExit("내 소재가 필요합니다: --background <파일...> 또는 --background-dir <폴더>")
    if not args.audio and not args.use_reference_audio:
        raise SystemExit("음악이 필요합니다: --audio <곡파일> 또는 --use-reference-audio")

    # 0) 참고 영상이 링크면 먼저 다운로드해 로컬 파일로.
    reference = args.reference
    if is_url(reference):
        _log(f"[벤치마크] 링크에서 참고 영상 다운로드 중: {reference}")
        reference = resolve_reference(reference, out_dir=".")
        _log(f"            → {reference}")

    # 1) 참고 영상 분석
    _log(f"[벤치마크] 참고 영상 분석 중: {reference}")
    profile = analyze_reference(
        reference,
        detect_subs=not args.no_subtitles,
        measure_music=not args.no_music,
        scene_threshold=args.scene_threshold,
    )
    print(summarize_profile(profile))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(profile.to_json())
        _log(f"[벤치마크] 프로파일 JSON 저장 → {args.out}")

    # 2) 사운드트랙 결정
    name = args.name or "benchmark_video"
    if args.use_reference_audio:
        if not profile.has_audio:
            raise SystemExit("참고 영상에 오디오가 없어 --use-reference-audio 를 쓸 수 없습니다.")
        audio_path = os.path.abspath(f"{name}.reference_audio.wav")
        _log(f"[벤치마크] 참고 영상 오디오 추출 → {audio_path}")
        extract_reference_audio(reference, audio_path)
    else:
        audio_path = args.audio

    # 3) 내 소재 + 오디오로 config 구성
    data = {"audio_path": audio_path}
    if args.background:
        data["background_paths"] = list(args.background)
    if args.background_dir:
        data["background_dir"] = args.background_dir
    config = from_dict(data)

    # 4) 벤치마크 프로파일을 config 에 반영(참고 영상과 유사한 편집).
    ov = profile_to_overrides(profile, style_override=args.style)
    extra = ov.pop("extra", {})
    for key, val in ov.items():
        setattr(config, key, val)
    config.extra.update(extra)
    _log(
        f"[벤치마크] 적용 → 스타일 '{config.style}' · {config.width}x{config.height} · "
        f"전환간격 {config.min_transition_gap:.2f}s · 소재모드 {config.footage_mode}"
        + (f" · 자막 y={extra['subtitle_y']}" if "subtitle_y" in extra else "")
    )

    # 5) 나머지 스칼라 오버라이드(가사/언어/드래프트 등).
    config.draft_name = name
    scalar = {
        "draft_folder": args.draft_folder,
        "clip_order": args.clip_order,
        "songbook": args.songbook,
        "song": args.song,
        "lyrics_file": args.lyrics_file,
        "lyrics_ko_file": args.lyrics_ko_file,
        "translate": args.translate,
        "language": args.language,
        "whisper_model": args.whisper_model,
        "lyrics_srt": args.lyrics_srt,
        "output_srt": args.output_srt,
        "script_file": args.script,
    }
    for key, val in scalar.items():
        if val is not None:
            setattr(config, key, val)

    # 초안 폴더 자동 감지.
    if not config.draft_folder:
        from .capcut_paths import default_draft_folder

        detected = default_draft_folder()
        if detected:
            config.draft_folder = detected
            _log(f"[초안폴더] 자동 감지 → {detected}")

    config.validate_paths()
    return _execute_pipeline(config, dry_run=args.dry_run)


def cmd_genplan(args: argparse.Namespace) -> int:
    """AI 소재 최소 제작 계획(필요한 최소 클립 수)을 계산해 출력합니다."""
    from .genplan import plan_generation, summarize_plan

    plan = plan_generation(
        args.song_duration,
        clip_len=args.clip_len,
        slow_floor=args.slow_floor,
        variety=args.variety,
    )
    print(summarize_plan(plan))
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
    run.add_argument(
        "--footage-mode",
        dest="footage_mode",
        choices=["auto", "coverage", "beat"],
        help="소재 모드 (auto=영상이면 슬로우채움, coverage=강제 슬로우, beat=비트 몽타주)",
    )
    run.add_argument("--slow-floor", dest="slow_floor", type=float,
                     help="최대 슬로우 속도 하한(0.1~1.0, 기본 0.5=최대 2배 느림)")
    run.add_argument("--draft-folder", dest="draft_folder", help="캡컷 초안 루트 폴더(생략 시 자동 감지)")
    run.add_argument("--name", help="초안(프로젝트) 이름")
    run.add_argument("--style", help=f"스타일 프리셋 ({', '.join(list_presets())})")
    run.add_argument("--songbook", help="곡별 정답 가사 엑셀(Mindtrack 형식)")
    run.add_argument("--song", help="송북 안에서 사용할 곡명(정답 가사·무드 가져옴)")
    run.add_argument("--lyrics-file", dest="lyrics_file", help="정답 가사 텍스트 파일")
    run.add_argument("--lyrics-ko", dest="lyrics_ko_file", help="줄 맞춤 한글 번역 파일(영한 이중 자막)")
    run.add_argument("--translate", dest="translate", action="store_true", default=None,
                     help="한글 파일 없을 때 자동 번역으로 이중 자막(deep-translator 필요)")
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
    run.add_argument("--script", help="대본 텍스트 파일(주면 Whisper 대신 대본을 비트에 맞춰 자막으로)")
    run.add_argument("--dry-run", action="store_true", help="초안 생성 없이 계획만 출력")
    run.set_defaults(func=cmd_run)

    # --- analyze: 참고 영상 분석만 -------------------------------------
    analyze = sub.add_parser("analyze", help="참고 영상 분석(편집 레시피 출력)")
    analyze.add_argument("--reference", required=True, help="분석할 참고 영상 파일 또는 유튜브/웹 링크")
    analyze.add_argument("--out", help="분석 결과 프로파일 JSON 저장 경로")
    analyze.add_argument("--no-subtitles", dest="no_subtitles", action="store_true",
                         help="자막 밴드 추정 생략(빠름)")
    analyze.add_argument("--no-music", dest="no_music", action="store_true",
                         help="오디오 템포 측정 생략(빠름)")
    analyze.add_argument("--scene-threshold", dest="scene_threshold", type=float, default=0.27,
                         help="장면 전환 감지 민감도(작을수록 컷 많이 감지, 기본 0.27)")
    analyze.set_defaults(func=cmd_analyze)

    # --- benchmark: 참고 영상 벤치마킹 → 내 클립으로 유사 영상 --------
    bench = sub.add_parser(
        "benchmark",
        help="참고 영상을 벤치마킹해 내 로컬 클립으로 유사한 영상 초안 생성",
    )
    bench.add_argument("--reference", required=True, help="벤치마킹할 참고 영상 파일 또는 유튜브/웹 링크")
    bench.add_argument("--background", nargs="+", help="내 영상/이미지 파일(여러 개 가능)")
    bench.add_argument("--background-dir", dest="background_dir", help="내 클립들이 담긴 폴더")
    bench.add_argument("--audio", help="사운드트랙(내 곡). 미지정 시 --use-reference-audio 필요")
    bench.add_argument("--use-reference-audio", dest="use_reference_audio",
                       action="store_true", help="참고 영상의 오디오를 그대로 사운드트랙으로 사용")
    bench.add_argument("--draft-folder", dest="draft_folder", help="캡컷 초안 루트 폴더(생략 시 자동 감지)")
    bench.add_argument("--name", help="초안(프로젝트) 이름")
    bench.add_argument("--style", help=f"스타일 강제 지정({', '.join(list_presets())}). 미지정 시 참고 영상에서 자동")
    bench.add_argument("--clip-order", dest="clip_order", choices=["sequential", "shuffle"],
                       help="클립 배치 순서")
    bench.add_argument("--out", help="분석 프로파일 JSON 저장 경로")
    bench.add_argument("--no-subtitles", dest="no_subtitles", action="store_true",
                       help="참고 영상 자막 밴드 추정 생략")
    bench.add_argument("--no-music", dest="no_music", action="store_true",
                       help="참고 영상 템포 측정 생략")
    bench.add_argument("--scene-threshold", dest="scene_threshold", type=float, default=0.27,
                       help="장면 전환 감지 민감도(기본 0.27)")
    # 가사/언어 옵션(run 과 동일)
    bench.add_argument("--songbook", help="곡별 정답 가사 엑셀(Mindtrack 형식)")
    bench.add_argument("--song", help="송북 안에서 사용할 곡명")
    bench.add_argument("--lyrics-file", dest="lyrics_file", help="정답 가사 텍스트 파일")
    bench.add_argument("--lyrics-ko", dest="lyrics_ko_file", help="줄 맞춤 한글 번역 파일")
    bench.add_argument("--translate", dest="translate", action="store_true", default=None,
                       help="자동 번역으로 영한 이중 자막")
    bench.add_argument("--language", help="Whisper 언어 코드(ko/en/…)")
    bench.add_argument("--whisper-model", dest="whisper_model", help="Whisper 모델 크기")
    bench.add_argument("--lyrics-srt", dest="lyrics_srt", help="준비된 SRT 사용(받아쓰기 생략)")
    bench.add_argument("--output-srt", dest="output_srt", help="받아쓴 가사 SRT 저장 경로")
    bench.add_argument("--script", help="대본 텍스트 파일(주면 Whisper 대신 대본을 비트에 맞춰 자막으로)")
    bench.add_argument("--dry-run", action="store_true", help="초안 생성 없이 계획만 출력")
    bench.set_defaults(func=cmd_benchmark)

    # --- genplan: AI 소재 최소 제작 계획 -------------------------------
    genplan = sub.add_parser(
        "genplan",
        help="AI 소재를 슬로우로 늘려 곡을 채울 때 필요한 최소 클립 수 계산",
    )
    genplan.add_argument("--song-duration", dest="song_duration", type=float, required=True,
                         help="곡 길이(초)")
    genplan.add_argument("--clip-len", dest="clip_len", type=float, default=5.0,
                         help="생성할 클립 1개 길이(초, 기본 5)")
    genplan.add_argument("--slow-floor", dest="slow_floor", type=float, default=0.5,
                         help="최대 슬로우 속도 하한(0.1~1.0, 기본 0.5=최대 2배 느림)")
    genplan.add_argument("--variety", type=float, default=1.0,
                         help="다양성 계수(>=1.0, 최소보다 여유 있게. 기본 1.0)")
    genplan.set_defaults(func=cmd_genplan)

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
