"""촬영 리스트(shot recipe) 순수 로직 테스트."""

from capcut_agent.shotlist import (
    CONSISTENCY_SUFFIX,
    build_shots,
    summarize_shots,
)


def test_count_respected():
    shots = build_shots("a car", is_vehicle=True, count=5)
    assert len(shots) == 5


def test_all_prompts_have_consistency_suffix():
    shots = build_shots("a matte black sports car", is_vehicle=True, count=6)
    assert all(CONSISTENCY_SUFFIX in s["prompt"] for s in shots)
    assert all("a matte black sports car" in s["prompt"] for s in shots)


def test_vehicle_includes_driver_pov():
    shots = build_shots("sports car", is_vehicle=True, count=5)
    names = " ".join(s["name"] for s in shots)
    assert "driver_pov" in names


def test_non_vehicle_excludes_driver_pov():
    shots = build_shots("a person hiking", is_vehicle=False, count=8)
    names = " ".join(s["name"] for s in shots)
    assert "driver_pov" not in names


def test_includes_first_person_pov():
    # 최소 1개 이상 1인칭(POV) 컷이 있어야 함.
    shots = build_shots("a car", is_vehicle=True, count=5, min_pov=1)
    pov = [s for s in shots if "pov" in s["name"] or "driver" in s["name"]]
    assert len(pov) >= 1


def test_min_pov_honored():
    shots = build_shots("a car", is_vehicle=True, count=6, min_pov=2)
    pov = [s for s in shots if "pov" in s["name"] or "driver" in s["name"]]
    assert len(pov) >= 2


def test_handheld_shake_in_pov_prompts():
    shots = build_shots("a car", is_vehicle=True, count=6, min_pov=2)
    pov = [s for s in shots if "pov" in s["name"]]
    # 1인칭(운전자 제외 walking POV)에는 손떨림(shake) 문구가 있어야 함.
    walking = [s for s in pov if "driver" not in s["name"]]
    assert walking, "walking POV 컷이 있어야 함"
    assert all("shake" in s["prompt"] for s in walking)


def test_names_are_indexed_and_unique():
    shots = build_shots("a car", is_vehicle=True, count=5)
    names = [s["name"] for s in shots]
    assert names[0].startswith("01_")
    assert len(set(names)) == len(names)


def test_count_zero_returns_empty():
    assert build_shots("x", count=0) == []


def test_more_than_library_cycles():
    # 라이브러리보다 많이 요청해도 개수를 채움.
    shots = build_shots("a car", is_vehicle=True, count=12)
    assert len(shots) == 12


def test_summarize_runs():
    text = summarize_shots(build_shots("a car", is_vehicle=True, count=5))
    assert "촬영 리스트" in text
    assert "5컷" in text
