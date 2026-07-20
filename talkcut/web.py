"""로컬 웹 서버 실행기.

    python -m talkcut.web
    python -m talkcut.web --port 8800 --draft-folder "<초안폴더>"

브라우저에서 http://127.0.0.1:8000 을 열어 영상을 드래그&드롭 하세요.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="talkcut.web", description="캡컷 에이전트 로컬 웹")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--draft-folder", dest="draft_folder", default=None,
                   help="캡컷 초안 폴더(생략 시 자동 감지)")
    args = p.parse_args(argv)

    try:
        import uvicorn  # noqa: WPS433
    except ImportError:
        print("웹 의존성이 없습니다. 설치: pip install fastapi uvicorn python-multipart",
              file=sys.stderr)
        return 1

    from .osdetect import check_environment, format_report
    from .webapp import create_app

    env = check_environment(check_draft_folder=(not args.draft_folder))
    print(format_report(env), file=sys.stderr)
    print(f"\n▶ 브라우저에서 열기:  http://{args.host}:{args.port}\n", file=sys.stderr)

    app = create_app(draft_folder=args.draft_folder)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
