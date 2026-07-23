"""벤치마크 순수 로직 테스트 (ffmpeg/librosa/numpy 불필요).

컷 통계 · 스타일 도출 · 자막 밴드 탐색 · 설정 오버라이드 변환을 검증합니다.
실제 영상/ffmpeg 을 쓰는 추출 함수는 여기서 테스트하지 않습니다.
"""

from capcut_agent.benchmark import (
    BenchmarkProfile,
    CutStats,
    SubtitleProfile,
    classify_aspect,
    compute_cut_stats,
    derive_style,
    locate_text_band,
    output_dimensions,
    profile_to_overrides,
    recommended_footage_mode,
    recommended_min_gap,
    subtitle_transform_y,
    summarize_profile,
)


# --- 비율 분류 -----------------------------------------------------------
def test_classify_aspect():
    assert classify_aspect(1080, 1920) == "vertical"
    assert classify_aspect(1080, 1080) == "square"
    assert classify_aspect(1920, 1080) == "horizontal"
    assert classify_aspect(0, 0) == "vertical"  # 방어적 기본값


def test_output_dimensions_keeps_standard_source():
    # 이미 표준 세로면 그대로.
    assert output_dimensions("vertical", 1080, 1920) == (1080, 1920)
    # 비표준 세로(예: 720x1280)는 비율 유지되면 그대로 사용.
    assert output_dimensions("vertical", 720, 1280) == (720, 1280)
    # 비율 불일치/미상 → 표준 캔버스.
    assert output_dimensions("horizontal", 0, 0) == (1920, 1080)
    assert output_dimensions("square", 0, 0) == (1080, 1080)


# --- 컷 통계 -------------------------------------------------------------
def test_compute_cut_stats_basic():
    # 10초 영상, 2·4·6·8초에 컷 → 5개 장면, 각 2초 간격.
    stats = compute_cut_stats([2.0, 4.0, 6.0, 8.0], 10.0)
    assert stats.count == 4
    assert stats.median_cut == 2.0
    assert stats.mean_cut == 2.0
    assert stats.fastest_cut == 2.0
    assert stats.cuts_per_min == 24.0  # 4컷 / (10/60분)


def test_compute_cut_stats_filters_out_of_range_and_sorts():
    stats = compute_cut_stats([8.0, -1.0, 2.0, 12.0, 4.0], 10.0)
    # 범위 밖(-1, 12) 제외, 정렬.
    assert stats.cut_times == [2.0, 4.0, 8.0]
    assert stats.count == 3


def test_compute_cut_stats_no_cuts():
    stats = compute_cut_stats([], 10.0)
    assert stats.count == 0
    assert stats.cuts_per_min == 0.0
    # 컷 없으면 전체가 한 장면 → 간격 = duration.
    assert stats.median_cut == 10.0


def test_compute_cut_stats_zero_duration():
    stats = compute_cut_stats([1.0, 2.0], 0.0)
    assert stats.count == 0
    assert stats.duration == 0.0


# --- 스타일 도출 ---------------------------------------------------------
def test_derive_style_energetic_fast():
    # 빠른 컷(0.8s) + 빠른 템포 → energetic
    assert derive_style(tempo=140, cuts_per_min=45, median_cut=0.8) == "energetic"


def test_derive_style_dreamy_slow():
    # 느린 컷(4s) + 느린 템포 → dreamy
    assert derive_style(tempo=80, cuts_per_min=8, median_cut=4.0) == "dreamy"


def test_derive_style_goosebump_mid():
    # 중간 편집 → goosebump
    assert derive_style(tempo=110, cuts_per_min=20, median_cut=2.0) == "goosebump"


def test_derive_style_no_tempo_uses_cuts():
    # 템포 미측정(0)이어도 컷 속도로 결정.
    assert derive_style(tempo=0, cuts_per_min=45, median_cut=0.8) == "energetic"
    assert derive_style(tempo=0, cuts_per_min=6, median_cut=4.0) == "dreamy"


# --- 전환 간격 / 소재 모드 ----------------------------------------------
def test_recommended_min_gap():
    assert recommended_min_gap(2.0) == 1.7          # 2.0 * 0.85
    assert recommended_min_gap(0.1) == 0.3          # 하한 클램프
    assert recommended_min_gap(100.0) == 3.5        # 상한 클램프
    assert recommended_min_gap(0.0) == 0.45         # 미측정 기본값


def test_recommended_footage_mode():
    assert recommended_footage_mode(0.8, 45) == "beat"     # 빠른 컷
    assert recommended_footage_mode(4.0, 8) == "coverage"  # 느린 컷
    assert recommended_footage_mode(2.0, 18) == "auto"     # 중간


# --- 자막 위치 -----------------------------------------------------------
def test_subtitle_transform_y_mapping():
    assert subtitle_transform_y(0.0) == 0.6         # 최상단(클램프)
    assert subtitle_transform_y(0.5) == 0.0         # 중앙
    assert subtitle_transform_y(1.0) == -0.85       # 최하단(클램프)
    # 전형적 하단 자막(0.85) → -0.7
    assert subtitle_transform_y(0.85) == -0.7


def test_locate_text_band_detects_lower_band():
    # 20줄 중 아래쪽(16~18)만 에너지가 높은 프로파일 → 하단 자막.
    energy = [1.0] * 20
    for i in (16, 17, 18):
        energy[i] = 5.0
    prof = locate_text_band(energy)
    assert prof.present is True
    assert prof.band == "lower"
    assert prof.vertical_pos > 0.7
    assert prof.contrast >= 1.6


def test_locate_text_band_flat_is_absent():
    # 균일한 프로파일(대비 낮음) → 자막 없음.
    prof = locate_text_band([2.0] * 20)
    assert prof.present is False
    assert prof.band == "none"


def test_locate_text_band_too_short():
    assert locate_text_band([1.0, 2.0]).present is False


# --- 프로파일 → 설정 오버라이드 ----------------------------------------
def _make_profile(**kw) -> BenchmarkProfile:
    base = dict(
        source="ref.mp4", width=1080, height=1920, fps=30.0, duration=30.0,
        aspect="vertical", has_audio=True, tempo=140.0,
        cuts=CutStats(cut_times=[1, 2, 3], duration=30.0, count=3,
                      cuts_per_min=40.0, median_cut=0.8, mean_cut=0.8,
                      p25_cut=0.7, fastest_cut=0.6),
        subtitles=SubtitleProfile(present=True, vertical_pos=0.85, band="lower",
                                  contrast=3.0),
        style="energetic",
    )
    base.update(kw)
    return BenchmarkProfile(**base)


def test_profile_to_overrides_full():
    ov = profile_to_overrides(_make_profile())
    assert ov["width"] == 1080 and ov["height"] == 1920
    assert ov["style"] == "energetic"
    assert ov["footage_mode"] == "beat"
    assert ov["min_transition_gap"] == recommended_min_gap(0.8)
    assert ov["extra"]["subtitle_y"] == subtitle_transform_y(0.85)
    assert ov["extra"]["benchmark_source"] == "ref.mp4"


def test_profile_to_overrides_style_override():
    ov = profile_to_overrides(_make_profile(), style_override="dreamy")
    assert ov["style"] == "dreamy"


def test_profile_to_overrides_no_subtitle_key_when_absent():
    prof = _make_profile(subtitles=SubtitleProfile(present=False))
    ov = profile_to_overrides(prof)
    assert "subtitle_y" not in ov["extra"]


def test_profile_json_roundtrip():
    prof = _make_profile()
    data = prof.to_dict()
    assert data["cuts"]["median_cut"] == 0.8
    assert data["subtitles"]["band"] == "lower"
    # JSON 직렬화 가능해야 함.
    assert '"source"' in prof.to_json()


def test_summarize_profile_runs():
    text = summarize_profile(_make_profile())
    assert "참고 영상 분석" in text
    assert "벤치마크 스타일 'energetic'" in text


# --- draft_builder 자막 위치 오버라이드 (pyCapCut 불필요) ----------------
def test_draft_builder_subtitle_base_y_from_extra():
    from capcut_agent.config import AgentConfig
    from capcut_agent.draft_builder import _subtitle_base_y

    # 벤치마크 값이 없으면 기존 기본 하단.
    cfg = AgentConfig(audio_path="a.mp3", draft_folder="/d", background_path="c.mp4")
    assert _subtitle_base_y(cfg) == -0.72

    # extra['subtitle_y'] 가 있으면 그 값을 사용(클램프 적용).
    cfg.extra["subtitle_y"] = -0.3
    assert _subtitle_base_y(cfg) == -0.3
    cfg.extra["subtitle_y"] = -5.0        # 범위 밖 → 클램프
    assert _subtitle_base_y(cfg) == -0.9
    cfg.extra["subtitle_y"] = "bad"       # 잘못된 값 → 기본값
    assert _subtitle_base_y(cfg) == -0.72
