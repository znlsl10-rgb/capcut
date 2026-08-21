"""threadscout — 해외 스레드(Meta Threads) 노출/확산 분석기.

키워드로 해외 Threads 공개 게시물을 수집해서
  · 노출(조회수)  · 공유/리포스트  · 댓글(대화)  · 팔로워 대비 도달 배수  · 초기 확산 속도
를 백분위 점수로 합산해 "터진 글"을 찾아내고, 그 글들의 공통 패턴(훅/포맷/시간대/키워드)을 뽑아냅니다.

구성
  models.py   원시 JSON → ThreadPost 정규화 (스크레이퍼별 필드명 차이 흡수)
  collect.py  Apify 액터 실행/데이터셋 수집 + 로컬 JSON 로드
  score.py    지표 계산 + 백분위 가중합 스코어링
  analyze.py  상위 글 공통 패턴 분석
  report.py   CSV / JSON / Markdown / HTML 리포트
  cli.py      python -m threadscout ...
  web.py      python -m threadscout.web  (로컬 웹 UI)
"""

from .models import ThreadPost, normalize_posts  # noqa: F401
from .score import ScoreWeights, score_posts  # noqa: F401

__all__ = ["ThreadPost", "normalize_posts", "ScoreWeights", "score_posts"]
