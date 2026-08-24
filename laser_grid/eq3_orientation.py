"""
[식 ③] 수직도·수평도 — 평면 법선 분석
========================================
θ_vert = arcsin(|n_y|)  — 벽면의 수직 기준 이탈 각도
θ_horiz = arccos(|n_y|/‖n‖)  — 바닥의 수평 기준 이탈 각도
"""
import numpy as np


def measure_verticality(plane_normal):
    """
    수직도 측정 — 벽면 법선의 y 성분이 0에 가까울수록 수직.
    
    Parameters
    ----------
    plane_normal : (3,) — (a, b, c)
    
    Returns
    -------
    theta_vert_deg : float (degree)
        벽면이 완벽한 수직선에서 얼마나 기울어졌는지
    """
    n = np.asarray(plane_normal, dtype=float)
    n = n / np.linalg.norm(n)
    
    theta_rad = np.arcsin(abs(n[1]))
    return float(np.degrees(theta_rad))


def measure_horizontality(plane_normal):
    """
    수평도 측정 — 바닥 법선이 깊이(Z)축과 평행할수록 수평.

    조사기 좌표계에서 바닥을 측정할 때 카메라 forward = (0,0,-1) 이므로
    완전 수평 바닥의 법선은 (0, 0, -1) → n[2] ≈ -1, n[1] ≈ 0.
    따라서 수평도 이탈각 = arccos(|n[2]|):
      - 완전 수평: |n[2]|=1 → 0°
      - 기울어질수록: |n[2]| 감소 → θh 증가

    [이전 버그] n[1](Y성분) 사용 → 완전수평에서 89.7° 출력
    [수정]     n[2](Z성분) 사용 → 완전수평에서 0° 출력  ✓

    Returns
    -------
    theta_horiz_deg : float (degree)
        바닥이 완벽한 수평면에서 얼마나 기울어졌는지
    """
    n = np.asarray(plane_normal, dtype=float)
    n = n / np.linalg.norm(n)

    # n[2]: 깊이(Z)방향 성분 — 완전 수평 바닥에서 abs(n[2])=1
    cos_theta = abs(n[2])
    cos_theta = np.clip(cos_theta, 0.0, 1.0)
    theta_rad = np.arccos(cos_theta)
    return float(np.degrees(theta_rad))


def judge_pass_fail(theta_deg, tolerance_deg=0.5):
    """
    시방서 허용 오차 비교.
    
    Returns
    -------
    is_pass : bool
    """
    return abs(theta_deg) <= tolerance_deg


# ============ 자체 검증 ============
if __name__ == "__main__":
    print("[식 ③] 수직도·수평도 검증")
    
    # 수직 벽면이 x축 기준 3° 기울어진 경우
    tilt_deg = 3.0
    rad = np.radians(tilt_deg)
    Rx = np.array([
        [1, 0, 0],
        [0, np.cos(rad), -np.sin(rad)],
        [0, np.sin(rad), np.cos(rad)]
    ])
    n_wall = Rx @ np.array([0, 0, -1])
    
    theta_v = measure_verticality(n_wall)
    print(f"  수직도: 측정 {theta_v:.4f}° (참값 {tilt_deg}°)")
    print(f"  오차: {abs(theta_v - tilt_deg):.6f}° "
          f"{'✓ PASS' if abs(theta_v - tilt_deg) < 1e-4 else '✗ FAIL'}")
    
    # 수평 바닥이 x축 기준 2° 기울어진 경우
    tilt_deg2 = 2.0
    rad2 = np.radians(tilt_deg2)
    Rx2 = np.array([
        [1, 0, 0],
        [0, np.cos(rad2), -np.sin(rad2)],
        [0, np.sin(rad2), np.cos(rad2)]
    ])
    n_floor = Rx2 @ np.array([0, 1, 0])
    
    theta_h = measure_horizontality(n_floor)
    print(f"  수평도: 측정 {theta_h:.4f}° (참값 {tilt_deg2}°)")
    print(f"  오차: {abs(theta_h - tilt_deg2):.6f}° "
          f"{'✓ PASS' if abs(theta_h - tilt_deg2) < 1e-4 else '✗ FAIL'}")
