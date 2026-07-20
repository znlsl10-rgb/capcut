"""뮤직비디오 로컬 웹 서버 실행기.

    python -m capcut_agent.web --songbook Mindtrack.xlsx
    python -m capcut_agent.web --songbook Mindtrack.xlsx --draft-folder "<초안폴더>" --port 8600

브라우저에서 http://127.0.0.1:8000 → 곡 선택 + mp3 드롭 → 뮤직비디오 드래프트.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="capcut_agent.web", description="캡컷 에이전트 · 뮤직비디오 웹")
    p.add_argument("--songbook", help="곡별 정답 가사 엑셀(Mindtrack 형식)")
    p.add_argument("--draft-folder", dest="draft_folder", default=None, help="캡컷 초안 폴더(생략 시 자동 감지)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    try:
        import uvicorn  # noqa: WPS433
    except ImportError:
        print("웹 의존성이 없습니다: pip install fastapi uvicorn python-multipart", file=sys.stderr)
        return 1

    from .webapp import create_app

    app = create_app(songbook=args.songbook, draft_folder=args.draft_folder)
    n = len(app.state.songs)
    print(f"[songbook] {args.songbook or '(미지정)'} · 곡 {n}개", file=sys.stderr)
    if not args.songbook:
        print("  ⚠️  --songbook 을 주면 곡 목록과 정답 가사가 로드됩니다.", file=sys.stderr)
    print(f"\n▶ 브라우저에서 열기:  http://{args.host}:{args.port}\n", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
