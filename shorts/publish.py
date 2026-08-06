"""게시(업로드) 매니페스트 + 업로드 경계.

## 왜 매니페스트인가
캡컷은 공식 내보내기 API가 없어, 완성 mp4 는 **캡컷 앱에서 내보내기(export)** 해야
합니다. 그래서 이 에이전트는 다음 두 단계로 나눕니다:

  1) 초안 생성(자동)  → 캡컷에서 초안을 열어 **내보내기** (사람 1클릭 또는 로컬 자동화)
  2) 업로드(반자동)    → 내보낸 mp4 경로를 매니페스트에 채우면 업로드 스텝이 사용

`write_publish_manifest()` 는 제목/설명/해시태그/자막/초안 경로를 한 JSON 으로 모아
"이 영상을 이렇게 올려라"를 기술합니다. mp4 경로만 채우면 업로드 가능해집니다.

## 업로드 방식(플랫폼별)
  - **틱톡**: higgsfield MCP(`tiktok_publish`)로 자동 게시 가능(연결 시).
  - **유튜브**: 공식 YouTube Data API v3 (OAuth) 필요. 자격증명이 있으면
    `youtube_upload()` 로 업로드합니다(아래 스텁 참고). 자격증명은 절대 코드/깃에
    커밋하지 말고 환경변수/시크릿으로 주입하세요.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .channel import ChannelProfile
from .metadata import build_metadata
from .script import MotivationScript


def write_publish_manifest(
    path: str,
    *,
    channel: ChannelProfile,
    script: MotivationScript,
    draft_path: str,
    srt_path: str,
    video_path: Optional[str] = None,
) -> str:
    """게시 매니페스트(JSON)를 작성합니다.

    video_path 가 None 이면 캡컷 내보내기 후 채워 넣도록 안내 필드를 남깁니다.
    """
    yt = build_metadata(script, channel, platform="youtube")
    tt = build_metadata(script, channel, platform="tiktok")

    if video_path:
        next_step = (
            "완성 mp4 가 준비됐습니다. higgsfield 로 업로드(media_upload) 후 "
            "tiktok_prepare_publish → tiktok_publish 로 게시하세요(게시 직전 동의 1회 필요)."
        )
    else:
        next_step = (
            "캡컷 초안을 열어 세로(9:16)로 내보낸 뒤, 그 mp4 경로를 'video_path' 에 "
            "채우면 업로드 스텝을 실행할 수 있습니다. (헤드리스 렌더를 켜면 이 과정이 생략됩니다)"
        )
    manifest = {
        "status": "ready_to_export" if not video_path else "ready_to_upload",
        "channel": channel.name,
        "topic": script.topic,
        "draft_path": draft_path,
        "srt_path": srt_path,
        "video_path": video_path,
        "_next_step": next_step,
        "youtube": {
            **yt.to_dict(),
            "privacy": "public",
            "categoryId": "22",  # People & Blogs
            "madeForKids": False,
        },
        "tiktok": tt.to_dict(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path


def load_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def youtube_upload(manifest_path: str) -> str:
    """매니페스트의 video_path 를 유튜브에 업로드합니다(자격증명 필요).

    실제 업로드는 YouTube Data API v3 + OAuth 자격증명이 있어야 하며, 이 함수는
    자격증명이 준비되기 전까지 명확한 안내와 함께 실패합니다. 자격증명(클라이언트
    시크릿, refresh token)은 환경변수/시크릿 매니저로 주입하고 절대 커밋하지 마세요.
    """
    manifest = load_manifest(manifest_path)
    video = manifest.get("video_path")
    if not video or not os.path.isfile(video):
        raise FileNotFoundError(
            "먼저 캡컷에서 초안을 mp4 로 내보내고, 매니페스트의 'video_path' 에 그 "
            "경로를 채워주세요. (캡컷은 자동 내보내기 API가 없습니다)"
        )
    raise NotImplementedError(
        "유튜브 자동 업로드는 YouTube Data API v3(OAuth) 자격증명이 필요합니다.\n"
        "설정 후 이 함수에서 google-api-python-client 로 videos.insert 를 호출하도록 "
        "연결하세요. 자격증명은 환경변수/시크릿으로만 주입하세요.\n"
        f"업로드 예정 파일: {video}\n"
        f"제목: {manifest.get('youtube', {}).get('title')}"
    )
