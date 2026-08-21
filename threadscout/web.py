"""로컬 웹 서버 실행기.

    python -m threadscout.web
    python -m threadscout.web --port 8800

브라우저에서 http://127.0.0.1:8010 접속.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="threadscout.web", description="해외 스레드 분석기 로컬 웹")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8010)
    args = p.parse_args(argv)

    try:
        import uvicorn  # noqa: WPS433
    except ImportError:
        print("웹 의존성이 없습니다. 설치: pip install fastapi uvicorn", file=sys.stderr)
        return 1

    from .coupang import PartnersClient
    from .webapp import create_app

    has_apify = bool(os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN"))
    print(f"[env] APIFY_TOKEN: {'✅' if has_apify else '❌ (수집 불가 — 재분석만 가능)'}", file=sys.stderr)
    print(f"[env] 쿠팡 파트너스 키: {'✅' if PartnersClient.from_env() else '❌ (제휴 링크 생성 불가)'}",
          file=sys.stderr)
    print(f"\n▶ 브라우저에서 열기:  http://{args.host}:{args.port}\n", file=sys.stderr)

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
