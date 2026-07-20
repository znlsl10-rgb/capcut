"""점프컷 드래프트 빌더 (pyCapCut).

입력 영상 하나를 여러 VideoSegment 로 쪼개, 보존 구간만 타임라인에 이어붙여
무음/컷 구간이 빠진 점프컷 드래프트를 만듭니다. 각 세그먼트는 원본의 오디오를
그대로 물고 가므로(토킹 영상) 별도 오디오 트랙이 필요 없습니다.

pyCapCut 함정 대응:
  - draft_meta_info.json 은 create_draft 가 자동 생성(초안 목록 노출).
  - 세그먼트는 겹치면 안 되므로 타임라인에 빈틈없이 연속 배치.
  - source_timerange 는 원본(보존 구간), target_timerange 는 결과 타임라인 위치.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

Interval = Tuple[float, float]
SEC_US = 1_000_000


def _us(seconds: float) -> int:
    return int(round(max(0.0, seconds) * SEC_US))


@dataclass
class JumpcutResult:
    draft_path: str
    n_segments: int
    kept_duration: float
    warnings: List[str] = field(default_factory=list)


def build_jumpcut_draft(
    video_path: str,
    keeps: Sequence[Interval],
    draft_folder: str,
    draft_name: str,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    fps: int = 30,
) -> JumpcutResult:
    """보존 구간(keeps)만 이어붙인 점프컷 드래프트를 생성합니다.

    Args:
        video_path: 입력 mp4/mov 절대경로.
        keeps: 보존 구간 [(start,end), ...] (초).
        draft_folder: 캡컷 초안 루트 폴더.
        draft_name: 초안(프로젝트) 이름.
        width/height: 출력 해상도. 미지정 시 원본 해상도 사용.
        fps: 프레임레이트.

    Returns:
        JumpcutResult (draft 경로, 세그먼트 수, 보존 길이, 경고).
    """
    import pycapcut as draft  # noqa: WPS433,F401
    from pycapcut import (  # noqa: WPS433
        DraftFolder,
        Timerange,
        TrackType,
        VideoMaterial,
        VideoSegment,
    )

    warnings: List[str] = []
    material = VideoMaterial(video_path)
    src_dur_us = int(getattr(material, "duration", 0) or 0)
    out_w = width or int(getattr(material, "width", 0) or 1080)
    out_h = height or int(getattr(material, "height", 0) or 1920)

    folder = DraftFolder(draft_folder)
    script = folder.create_draft(draft_name, out_w, out_h, fps=fps, allow_replace=True)
    script.add_track(TrackType.video, "main")

    cursor_us = 0
    n = 0
    for start_s, end_s in keeps:
        s_us = _us(start_s)
        dur_us = _us(end_s) - s_us
        if dur_us <= 0:
            continue
        # 원본 길이를 넘어가지 않도록 방어.
        if src_dur_us and s_us + dur_us > src_dur_us:
            dur_us = max(0, src_dur_us - s_us)
        if dur_us <= 0:
            continue
        source = Timerange(s_us, dur_us)
        target = Timerange(cursor_us, dur_us)
        try:
            seg = VideoSegment(material, target, source_timerange=source)
            script.add_segment(seg, "main")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"세그먼트 [{start_s:.2f}-{end_s:.2f}] 스킵: {exc}")
            continue
        cursor_us += dur_us
        n += 1

    if n == 0:
        raise ValueError("배치된 세그먼트가 없습니다. 보존 구간을 확인하세요.")

    script.save()
    return JumpcutResult(
        draft_path=os.path.join(draft_folder, draft_name),
        n_segments=n,
        kept_duration=round(cursor_us / SEC_US, 3),
        warnings=warnings,
    )
