"""shorts.metadata + channel 순수 로직 테스트."""

from __future__ import annotations

from shorts.channel import ChannelProfile, default_channel, from_dict
from shorts.metadata import build_metadata
from shorts.script import parse_script


def _script():
    return parse_script(
        "[hook] 늦잠 자는 동안 그들은 하루를 이겼다\n"
        "[body] 목표에 맞춰 일어난다\n[cta] 구독하고 함께 성장해요",
        topic="새벽 루틴 성공 습관",
    )


def test_channel_from_dict_requires_name():
    try:
        from_dict({"niche": "x"})
        assert False, "name 없으면 예외여야 함"
    except ValueError:
        pass


def test_channel_resolved_style_from_tone():
    assert ChannelProfile(name="c", tone="강렬").resolved_style() == "motivation"
    assert ChannelProfile(name="c", tone="시네마틱").resolved_style() == "cinematic"
    assert ChannelProfile(name="c", style="retro").resolved_style() == "retro"


def test_channel_signature_adds_at():
    assert ChannelProfile(name="c", handle="myhandle").signature() == "@myhandle"
    assert ChannelProfile(name="브랜드").signature() == "브랜드"


def test_hashtags_dedup_and_prefix():
    ch = ChannelProfile(name="c", hashtags=["동기부여", "#동기부여", "#자기계발"])
    assert ch.normalized_hashtags() == ["#동기부여", "#자기계발"]


def test_youtube_metadata_has_shorts_tag_and_title():
    meta = build_metadata(_script(), default_channel(), platform="youtube")
    assert meta.platform == "youtube"
    assert any(h.lower() == "#shorts" for h in meta.hashtags)
    assert "늦잠" in meta.title
    assert "구독" in meta.description


def test_tiktok_metadata_has_fyp():
    meta = build_metadata(_script(), default_channel(), platform="tiktok")
    assert any(h == "#fyp" for h in meta.hashtags)


def test_metadata_respects_max_hashtags():
    ch = ChannelProfile(name="c", hashtags=[f"#t{i}" for i in range(20)])
    meta = build_metadata(_script(), ch, platform="youtube", max_hashtags=3)
    assert len(meta.hashtags) == 3


def test_seo_tags_include_niche():
    meta = build_metadata(_script(), default_channel(), platform="youtube")
    assert any("동기부여" in t for t in meta.tags)


def test_long_hook_title_truncated():
    long_hook = "훅 " * 60
    s = parse_script(f"[hook] {long_hook}\n[body] b\n[cta] 구독", topic="t")
    meta = build_metadata(s, default_channel(), platform="youtube")
    assert len(meta.title) <= 90
