"""동기부여 쇼츠 에이전트 (Motivation Shorts).

성공 동기부여 유튜브 채널의 **구독자 성장**을 목표로, 내 소재(영상/이미지)를
편집해 **세로 쇼츠**를 만들고 **게시 메타데이터**까지 자동 생성하는 레이어입니다.

기존 `capcut_agent` 편집 엔진을 그대로 재사용합니다:

    나레이션 음성  ← (뮤직비디오의 "노래 오디오")
    대본 텍스트    ← (뮤직비디오의 "정답 가사") → 나레이션에 강제정렬해 자막 타이밍
    내 소재         ← (뮤직비디오의 "배경 영상")   → 컷 편집
    세로 1080x1920  ← (이미 기본값)

이 패키지가 더하는 것("콘텐츠 두뇌"):

    channel.py   채널 브랜딩/톤/CTA/해시태그 프로필 (노션 브랜딩이 여기 들어감)
    topics.py    성공 동기부여 주제 뱅크 + 결정론적 로테이션(오늘의 주제)
    script.py    대본 → 훅/본문/CTA 라인 + 쇼츠용 짧은 자막 분할
    metadata.py  유튜브/틱톡 제목·설명·해시태그·태그 생성
    pipeline.py  나레이션 + 소재 + 대본 → 세로 캡컷 초안 + 메타데이터 산출
    publish.py   게시 매니페스트 작성 + 업로드 경계(유튜브/틱톡) 문서화

순수 로직(channel/topics/script/metadata)은 무거운 의존성 없이 테스트됩니다.
"""

from __future__ import annotations

__all__ = [
    "ChannelProfile",
    "load_channel",
    "MotivationScript",
    "ScriptLine",
    "parse_script",
    "split_captions",
    "PublishMetadata",
    "build_metadata",
    "pick_topics",
    "daily_plan",
    "Caption",
    "RenderStyle",
    "render_short",
    "NarrationRequest",
    "synthesize",
    "build_short",
    "ShortResult",
]

from .channel import ChannelProfile, load_channel
from .metadata import PublishMetadata, build_metadata
from .pipeline import ShortResult, build_short
from .render import Caption, RenderStyle, render_short
from .script import MotivationScript, ScriptLine, parse_script, split_captions
from .topics import daily_plan, pick_topics
from .voice import NarrationRequest, synthesize
