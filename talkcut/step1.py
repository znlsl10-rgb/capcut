"""Step 1 CLI: 입력 영상 → 무음 제거 점프컷 드래프트 (UI 없음).

핵심 검증 단계. 실행 후 캡컷에서 초안을 열어 **직접 재생**해 확인하세요.
빌드 성공은 검증이 아닙니다.

사용:
    python -m talkcut.step1 input.mp4
    python -m talkcut.step1 input.mp4 --draft-folder "<초안폴더>" --name my_cut
    python -m talkcut.step1 input.mp4 --threshold-db -38 --min-silence 0.4 --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="talkcut.step1",
        description="무음 제거 점프컷 드래프트 생성 (캡컷 에이전트 1단)",
    )
    p.add_argument("video", nargs="?", help="입력 mp4/mov 경로")
    p.add_argument("--draft-folder", dest="draft_folder", help="캡컷 초안 폴더(생략 시 자동 감지)")
    p.add_argument("--name", default=None, help="초안 이름(기본: 파일명 + _jumpcut)")
    p.add_argument("--threshold-db", type=float, default=-35.0, help="무음 판정 dB (낮을수록 엄격)")
    p.add_argument("--min-silence", type=float, default=0.35, help="무음으로 볼 최소 길이(초)")
    p.add_argument("--pad", type=float, default=0.06, help="보존 구간 양끝 여유(초)")
    p.add_argument("--min-keep", type=float, default=0.20, help="이보다 짧은 보존 조각 버림(초)")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--dry-run", action="store_true", help="드래프트 생성 없이 컷 계획만 출력")
    p.add_argument("--check", action="store_true", help="환경 점검(Step 0)만 실행")
    return p


def _resolve_draft_folder(arg: Optional[str]) -> Optional[str]:
    if arg:
        return arg
    try:
        from capcut_agent.capcut_paths import default_draft_folder

        return default_draft_folder()
    except Exception:  # noqa: BLE001
        return None


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    from .osdetect import check_environment, format_report

    env = check_environment(check_draft_folder=(not args.draft_folder))
    _log(format_report(env))

    if args.check:
        return 0

    if not args.video:
        _log("오류: 입력 영상 경로가 필요합니다. (예: python -m talkcut.step1 input.mp4)")
        return 1
    if not os.path.isfile(args.video):
        _log(f"오류: 파일을 찾을 수 없습니다: {args.video}")
        return 1

    # 무음 감지
    from .audio_silence import analyze_silence

    _log(f"[silence] 분석 중: {args.video}")
    result = analyze_silence(
        args.video,
        threshold_db=args.threshold_db,
        min_silence=args.min_silence,
        pad=args.pad,
        min_keep=args.min_keep,
    )
    _log(
        f"[silence] 길이 {result.duration:.1f}s · 무음 {len(result.silences)}곳 · "
        f"보존 컷 {len(result.keeps)}개 · 제거 {result.removed:.1f}s "
        f"({result.removed / result.duration * 100 if result.duration else 0:.0f}%)"
    )

    if args.dry_run:
        _log("[dry-run] 컷 계획(앞 10개):")
        for s, e in result.keeps[:10]:
            _log(f"    keep {s:6.2f} → {e:6.2f}  ({e - s:.2f}s)")
        return 0

    draft_folder = _resolve_draft_folder(args.draft_folder)
    if not draft_folder:
        _log("오류: 캡컷 초안 폴더를 찾지 못했습니다. --draft-folder 로 지정하거나 캡컷을 1회 실행하세요.")
        return 1
    if not os.path.isdir(draft_folder):
        _log(f"오류: 초안 폴더가 존재하지 않습니다: {draft_folder}")
        return 1

    name = args.name or (os.path.splitext(os.path.basename(args.video))[0] + "_jumpcut")

    from .jumpcut import build_jumpcut_draft

    _log(f"[draft] 점프컷 드래프트 생성 중 → {os.path.join(draft_folder, name)}")
    res = build_jumpcut_draft(
        os.path.abspath(args.video), result.keeps, draft_folder, name, fps=args.fps
    )
    for w in res.warnings:
        _log(f"  ⚠️  {w}")
    _log(f"[draft] 완료: 세그먼트 {res.n_segments}개 · 결과 길이 {res.kept_duration:.1f}s")
    _log("")
    _log("✅ 다음: 캡컷을 (재)시작 → 초안 목록에서 열기 → **직접 재생해 검증**하세요.")
    _log("   (빌드 성공 ≠ 검증. 컷 타이밍/말 잘림 여부는 재생으로만 확인됩니다.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
