#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
회귀 검증 — 기존 PDF 검증값이 그대로 재현되는지 + 영역별 검측이 정답과 맞는지
========================================================================
Isaac Sim 없이 도는 검증만 모았다. 렌더링·선검출까지 포함한 검증은
Isaac 환경에서 inspection.py 를 돌려야 한다.

실행:  python3 tests/test_regression.py
========================================================================
"""
import sys, os
import numpy as np
import importlib.util as ilu

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def _load(name):
    spec = ilu.spec_from_file_location(name, os.path.join(ROOT, f"{name}.py"))
    m = ilu.module_from_spec(spec); spec.loader.exec_module(m)
    return m


EQ1 = _load("eq1_triangulation")
EQ2 = _load("eq2_plane_fit")
EQ3 = _load("eq3_orientation")
EQ5 = _load("eq5_region_assign")
PIPE = _load("pipeline_region")
SYN = _load("synth_scene")

_FAILS = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)
    return cond


def test_eq1_triangulation():
    """PDF 5.1: 삼각측량 깊이복원오차 ≈ 0mm"""
    print("\n[1] eq1 삼각측량 — PDF 검증값 재현")
    f, b, cx, cy = 1593.0, 0.150, 1224.0, 1024.0
    for Z_true in (0.5, 1.0, 1.5, 2.0):
        alpha, beta = np.radians(10.0), np.radians(5.0)
        X_t, Y_t = Z_true * np.tan(alpha), Z_true * np.tan(beta)
        u = f * (X_t - b) / Z_true + cx
        v = f * Y_t / Z_true + cy
        _, _, Z = EQ1.triangulate_point(u, v, alpha, beta, f, b, cx, cy)
        err_mm = abs(Z - Z_true) * 1000
        check(f"Z={Z_true}m 복원오차 {err_mm:.6f}mm < 0.001mm", err_mm < 1e-3)


def test_eq3_backward_compat():
    """v1 좌표축 규약이 v2 기본값으로 그대로 재현되는지"""
    print("\n[2] eq3 하위호환 — v1 규약 재현")

    def rx(d):
        r = np.radians(d)
        return np.array([[1, 0, 0], [0, np.cos(r), -np.sin(r)],
                         [0, np.sin(r), np.cos(r)]])

    n_wall = rx(0.5) @ np.array([0, 0, -1.0])
    tv = EQ3.measure_verticality(n_wall)
    check(f"수직도 기본 ĝ: {tv:.4f}° (참값 0.5°)", abs(tv - 0.5) < 1e-6)

    n_floor = rx(0.3) @ np.array([0, 0, -1.0])
    th = EQ3.measure_horizontality(n_floor)
    check(f"수평도 바닥규약: {th:.4f}° (참값 0.3°)", abs(th - 0.3) < 1e-6)

    # 회전 불변성 — 점군과 중력을 같이 돌리면 결과가 변하지 않아야 한다
    Rt = rx(37.0)
    tv2 = EQ3.measure_verticality(Rt @ n_wall, g_hat=Rt @ EQ3.G_UPRIGHT)
    check(f"장비 37° 기울임 불변: {tv2:.4f}° (참값 0.5°)", abs(tv2 - 0.5) < 1e-6)


def test_gravity_paths_agree():
    """IMU 경로와 카메라 자세 경로가 같은 ĝ 를 내는지"""
    print("\n[3] 중력 경로 일치 — IMU vs 카메라 자세")
    for pitch in (0.0, 22.0, 90.0):
        td = np.radians(pitch)
        view = np.array([0.0, np.cos(td), -np.sin(td)])
        up = np.array([0.0, 0.0, 1.0])
        if abs(float(view @ up)) > 0.9:
            up = np.array([0.0, 1.0, 0.0])
        right = np.cross(view, up); right /= np.linalg.norm(right)
        down = np.cross(view, right); down /= np.linalg.norm(down)
        R = np.column_stack([right, down, view])
        g_cam = EQ3.gravity_from_camera_rotation(R)
        g_expect = np.array([0.0, np.cos(td), np.sin(td)])
        err = float(np.linalg.norm(g_cam - g_expect))
        check(f"pitch {pitch:4.1f}° → ĝ 오차 {err:.2e}", err < 1e-9)


def test_tls_plane_vs_legacy():
    """경사면에서 TLS 가 필요한 이유 + 정면에서 회귀 없음"""
    print("\n[4] eq2 TLS 평면적합 — 경사면 정확도 / 정면 무회귀")
    rng = np.random.default_rng(3)
    grazing = np.column_stack([rng.uniform(-.6, .6, 400), np.full(400, 0.8),
                               rng.uniform(.5, 2.5, 400)]) \
        + rng.normal(0, 5e-4, (400, 3))

    def ang(n, truth):
        n = np.asarray(n[:3], float); n /= np.linalg.norm(n)
        return float(np.degrees(np.arccos(min(1.0, abs(float(n @ truth))))))

    old, _ = EQ2.fit_plane_ransac(grazing, threshold=0.01)
    new, _ = EQ2.fit_plane_tls_ransac(grazing, threshold=0.005)
    e_old, e_new = ang(old, [0, 1, 0]), ang(new, [0, 1, 0])
    check(f"경사면 TLS 법선오차 {e_new:.4f}° ≤ 0.05° (기존 {e_old:.2f}°)",
          e_new <= 0.05)
    check(f"기존 방식이 실제로 실패함을 확인 ({e_old:.2f}° > 0.5°)", e_old > 0.5)

    front = np.column_stack([rng.uniform(-.5, .5, 400), rng.uniform(-.4, .4, 400),
                             np.full(400, 1.2)]) + rng.normal(0, 5e-4, (400, 3))
    o2, _ = EQ2.fit_plane_ransac(front, threshold=0.01)
    n2, _ = EQ2.fit_plane_tls_ransac(front, threshold=0.005)
    d = abs(ang(o2, [0, 0, 1]) - ang(n2, [0, 0, 1]))
    check(f"정면 벽 회귀 없음 (두 방식 차 {d:.4f}° < 0.01°)", d < 0.01)


def test_axis_fit():
    """동바리 축 적합 정확도"""
    print("\n[5] eq2 축 적합 — 동바리 Ø48.6mm")
    rng = np.random.default_rng(0)
    for tilt in (0.0, 0.6, 1.2, 3.0):
        d = EQ3.normalize(np.array(
            [0.0, -np.cos(np.radians(tilt)), np.sin(np.radians(tilt))]))
        e1, e2 = EQ2.plane_tangent_basis(d)
        t = rng.uniform(0, 2.4, 300); ph = rng.uniform(-1.0, 1.0, 300)
        P = (np.outer(t, d) + 0.0243 * (np.cos(ph)[:, None] * e1
                                        + np.sin(ph)[:, None] * e2)
             + rng.normal(0, 8e-4, (300, 3)))
        res = EQ2.fit_axis_pca(P)
        theta = EQ3.measure_axis_verticality(res["direction"],
                                             g_hat=[0, 1, 0])
        err = abs(theta - tilt)
        check(f"기울기 {tilt}° → 측정 {theta:.4f}° 오차 {err:.4f}° < 0.1°",
              err < 0.1)


def test_region_pipeline():
    """합성 씬 전 구간 — 두 세그멘테이션 백엔드"""
    print("\n[6] 영역별 검측 파이프라인 — 합성 씬 (벽+바닥+동바리)")
    scene = SYN.build_scene()
    gt = scene["gt"]
    want = {"wall": "wall_verticality_deg",
            "floor": "floor_horizontality_deg",
            "shoring": "shoring_verticality_deg"}

    for backend in ("gt", "geom"):
        res = PIPE.inspect_capture(
            scene["lines_pixels"], scene["line_angles"],
            scene["camera_params"], scene["R_world_cam"],
            label_map=(scene["label_map"] if backend == "gt" else None),
            id_to_semantic=(scene["id_to_semantic"] if backend == "gt" else None),
            rgb_off=scene["rgb_off"], backend=backend)

        # inspect_capture 가 카메라 자세에서 유도한 ĝ 가 씬의 ĝ 와 같아야 한다
        gerr = float(np.linalg.norm(
            np.array(res["gravity_laser_frame"]) - scene["g_hat"]))
        check(f"[{backend}] 카메라 자세 유도 ĝ 오차 {gerr:.2e}", gerr < 1e-6)

        best = {}
        for r in res["regions"]:
            if r["status"] != "measured":
                continue
            c = r["class"]
            if c not in best or r["n_points"] > best[c]["n_points"]:
                best[c] = r
        for cls, key in want.items():
            r = best.get(cls)
            if not check(f"[{backend}] {cls} 영역 검출됨", r is not None):
                continue
            err = abs(r["theta_deg"] - gt[key])
            check(f"[{backend}] {cls} {r['theta_deg']:.4f}° "
                  f"(정답 {gt[key]}°) 오차 {err:.4f}° ≤ 0.5°", err <= 0.5)

        w = best.get("wall")
        if w and w["flatness"]["applicable"]:
            fm = w["flatness"]["max_dev_mm"]
            check(f"[{backend}] 벽 요철 검출 {fm:.2f}mm "
                  f"(정답 {gt['wall_bump_mm']}mm, 과소보고 한계 내)",
                  0.5 * gt["wall_bump_mm"] <= fm <= 1.5 * gt["wall_bump_mm"])


def test_boundary_rejection():
    """경계 오염 제거 — 깊이 불연속"""
    print("\n[7] eq5 경계 정제")
    tbl = {"uv": np.zeros((40, 2)), "seq": np.arange(40),
           "lid": np.array(["V0"] * 40, dtype=object),
           "xyz": np.column_stack([np.zeros(40), np.zeros(40),
                                   np.r_[np.full(20, 1.2), np.full(20, 2.0)]])}
    bad = EQ5.mark_depth_discontinuity(tbl)
    check(f"벽1.2m→바닥2.0m 경계에서 2점 제거 (실제 {int(bad.sum())})",
          bad.sum() == 2 and bad[19] and bad[20])

    m = np.zeros((60, 60), bool); m[20:40, 20:40] = True
    check(f"마스크 3px 침식 400→{int(EQ5.erode_mask(m, 3).sum())}px",
          EQ5.erode_mask(m, 3).sum() == 196)


def main():
    print("=" * 70)
    print("레이저 그리드 품질검측 — 회귀 검증")
    print("=" * 70)
    for t in (test_eq1_triangulation, test_eq3_backward_compat,
              test_gravity_paths_agree, test_tls_plane_vs_legacy,
              test_axis_fit, test_region_pipeline, test_boundary_rejection):
        t()
    print("\n" + "=" * 70)
    if _FAILS:
        print(f"실패 {len(_FAILS)}건:")
        for f in _FAILS:
            print(f"  - {f}")
        return 1
    print("전체 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
