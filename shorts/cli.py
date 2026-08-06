"""동기부여 쇼츠 에이전트 CLI.

사용 예:
    # 오늘/이번 주 주제 뽑기(결정론적)
    python -m shorts topics --days 7 --seed 2026-08

    # 대본만으로 계획 + 게시 메타데이터 미리보기(라이브러리 불필요)
    python -m shorts plan --script script.txt --channel channel.yaml --topic "새벽 루틴"

    # 게시 메타데이터(JSON) 출력
    python -m shorts metadata --script script.txt --channel channel.yaml --platform youtube

    # 실제 세로 캡컷 초안 생성 (나레이션 + 내 소재 + 대본)
    python -m shorts build \\
        --script script.txt --channel channel.yaml \\
        --narration voice.mp3 --footage-dir ./clips \\
        --name morning_routine
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import List, Optional

from .channel import ChannelProfile, default_channel, load_channel
from .metadata import build_metadata
from .script import MotivationScript, parse_script


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _load_channel(path: Optional[str]) -> ChannelProfile:
    if path:
        return load_channel(path)
    _log("[채널] --channel 미지정 → 기본 프로필 사용(브랜딩 확정 시 YAML 로 교체하세요)")
    return default_channel()


def _load_script(args: argparse.Namespace) -> MotivationScript:
    topic = args.topic or ""
    if args.script:
        with open(args.script, "r", encoding="utf-8") as f:
            raw = f.read()
    elif args.text:
        raw = args.text
    else:
        raise SystemExit("대본이 필요합니다: --script <파일> 또는 --text \"...\"")
    return parse_script(raw, topic=topic)


_MEDIA_EXTS = ("mp4", "mov", "mkv", "webm", "avi", "m4v", "jpg", "jpeg", "png", "webp")


def _collect_footage(args: argparse.Namespace) -> List[str]:
    paths: List[str] = []
    if args.footage_dir:
        found: List[str] = []
        for ext in _MEDIA_EXTS:
            found.extend(glob.glob(os.path.join(args.footage_dir, f"*.{ext}")))
            found.extend(glob.glob(os.path.join(args.footage_dir, f"*.{ext.upper()}")))
        paths.extend(sorted(found))
    if args.footage:
        paths.extend(args.footage)
    return paths


def cmd_topics(args: argparse.Namespace) -> int:
    from .topics import daily_plan

    plan = daily_plan(args.days, per_day=args.per_day, seed=args.seed, category=args.category)
    for day in sorted(plan):
        for t in plan[day]:
            print(f"Day {day + 1:>2}  [{t.category}] {t.title}  —  {t.angle}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    from .pipeline import plan_short

    channel = _load_channel(args.channel)
    script = _load_script(args)
    print(plan_short(script, channel, max_caption_chars=args.max_caption_chars))
    return 0


def cmd_metadata(args: argparse.Namespace) -> int:
    channel = _load_channel(args.channel)
    script = _load_script(args)
    meta = build_metadata(script, channel, platform=args.platform)
    print(json.dumps(meta.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from .pipeline import build_short

    channel = _load_channel(args.channel)
    script = _load_script(args)
    footage = _collect_footage(args)

    if not args.dry_run:
        if not args.narration:
            raise SystemExit("나레이션 음성이 필요합니다: --narration <파일> (또는 --dry-run)")
        if not footage:
            raise SystemExit("내 소재가 필요합니다: --footage <파일...> 또는 --footage-dir <폴더>")

    _log(f"[쇼츠] 주제 '{script.topic or '(미지정)'}' · 프리셋 {channel.resolved_style()}")
    result = build_short(
        script,
        channel,
        narration_audio=args.narration or "",
        footage=footage,
        draft_folder=args.draft_folder,
        draft_name=args.name,
        output_dir=args.output_dir,
        max_caption_chars=args.max_caption_chars,
        whisper_model=args.whisper_model,
        clip_order=args.clip_order,
        render=not args.no_render,
        make_draft=args.make_draft,
        align=not args.no_align,
        dry_run=args.dry_run,
    )
    for w in result.warnings:
        _log(f"  ⚠️  {w}")
    _log(f"[메타] {result.metadata_path}")
    _log(f"[자막] {result.srt_path}")
    _log(f"[게시] {result.manifest_path}")
    if args.dry_run:
        _log("[dry-run] 렌더/초안 없이 메타/자막만 생성. --dry-run 을 빼면 실제 mp4 를 렌더합니다.")
        return 0
    if result.video_path:
        _log(f"[완성] {result.video_path}  ← 이 mp4 를 틱톡에 올리면 끝")
    if result.draft_path:
        _log(f"[초안] {result.draft_path} (캡컷에서 손보기용)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shorts",
        description="성공 동기부여 유튜브 쇼츠 자동 제작·게시 에이전트",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # 공통 대본/채널 인자 헬퍼
    def add_script_args(sp):
        sp.add_argument("--script", help="대본 텍스트 파일")
        sp.add_argument("--text", help="대본을 인라인으로 직접 전달")
        sp.add_argument("--channel", help="채널 프로필 YAML")
        sp.add_argument("--topic", help="이 영상의 주제(메타/내부용)")
        sp.add_argument("--max-caption-chars", dest="max_caption_chars", type=int, default=16,
                        help="자막 한 줄 최대 글자 수(기본 16)")

    t = sub.add_parser("topics", help="동기부여 주제 로테이션 뽑기")
    t.add_argument("--days", type=int, default=7, help="며칠치 뽑을지")
    t.add_argument("--per-day", dest="per_day", type=int, default=1, help="하루 몇 개")
    t.add_argument("--seed", default="plan", help="재현용 시드(같은 시드=같은 결과)")
    t.add_argument("--category", help="카테고리 필터(루틴/마인드셋/실행/부/확신/집중)")
    t.set_defaults(func=cmd_topics)

    pl = sub.add_parser("plan", help="계획 + 게시 메타 미리보기(라이브러리 불필요)")
    add_script_args(pl)
    pl.set_defaults(func=cmd_plan)

    md = sub.add_parser("metadata", help="게시 메타데이터 JSON 출력")
    add_script_args(md)
    md.add_argument("--platform", choices=["youtube", "tiktok"], default="youtube")
    md.set_defaults(func=cmd_metadata)

    b = sub.add_parser("build", help="세로 캡컷 초안 생성(나레이션+소재+대본)")
    add_script_args(b)
    b.add_argument("--narration", help="나레이션 음성 파일(내 목소리 또는 TTS)")
    b.add_argument("--footage", nargs="+", help="내 소재 파일들(영상/이미지)")
    b.add_argument("--footage-dir", dest="footage_dir", help="내 소재 폴더")
    b.add_argument("--draft-folder", dest="draft_folder", help="캡컷 초안 루트 폴더(생략 시 자동 감지)")
    b.add_argument("--name", default="motiv_short", help="초안(프로젝트) 이름")
    b.add_argument("--output-dir", dest="output_dir", default=".", help="메타/자막/매니페스트 저장 폴더")
    b.add_argument("--whisper-model", dest="whisper_model", default="small", help="Whisper 모델 크기")
    b.add_argument("--clip-order", dest="clip_order", choices=["sequential", "shuffle"],
                   default="sequential", help="소재 배치 순서")
    b.add_argument("--no-render", dest="no_render", action="store_true",
                   help="완성 mp4 렌더를 끔(캡컷 초안만 만들 때)")
    b.add_argument("--make-draft", dest="make_draft", action="store_true",
                   help="캡컷 초안도 함께 생성(손보기용, pyCapCut 필요)")
    b.add_argument("--no-align", dest="no_align", action="store_true",
                   help="Whisper 강제정렬 끄고 나레이션 길이에 비례해 자막 분배")
    b.add_argument("--dry-run", action="store_true", help="렌더/초안 없이 메타/자막만 생성")
    b.set_defaults(func=cmd_build)

    return p


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
