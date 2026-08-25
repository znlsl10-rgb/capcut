#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibration.py — 캘리브레이션 데이터 단일 출처
========================================================================
검측 알고리즘이 쓰는 상수를 한곳에 모은다. 이전에는 inspection.py 와
synth_scene.py 가 같은 값을 따로 들고 있었고 A_선검출·eq5 는 또 다른
기본값을 갖고 있어, 한쪽만 고치면 조용히 어긋났다.

【데이터 구분 — PDF 3.1】
  A. 매 촬영 데이터   촬영할 때마다 하드웨어가 보내는 것
  B. 캘리브레이션     출고 시 1회 측정해 모듈에 저장하는 것
  B 의 정확도가 곧 측정 정확도다. 기선 실측값과 레이저 발사각이
  부정확하면 알고리즘이 정확해도 결과가 틀어진다.

【값의 출처를 세 등급으로 구분한다】
  spec    PDF 하드웨어 사양에서 유도 (부품 번호가 있는 실물 기준)
  design  설계 고정값 (용역서에 명시)
  assumed 가정값 — 출고 전 실측으로 대체해야 함

  assumed 로 남은 항목이 현재 측정 신뢰도의 상한이다.
========================================================================
"""
import numpy as np

# =====================================================================
# 하드웨어 사양 (PDF 2.2)
# =====================================================================
LENS_FOCAL_MM = 12.0        # spec  렌즈 12mm F2.0
PIXEL_PITCH_UM = 3.45       # spec  Sony IMX264, 3.45µm
IMAGE_W = 2448              # spec  2448 × 2048 (5MP)
IMAGE_H = 2048              # spec
BASELINE_M = 0.150          # design 카메라–레이저 광축 150mm

# DOE 격자
N_VERTICAL = 21             # design 수직선 수
N_HORIZONTAL = 21           # design 수평선 수

# 측정 거리 (PDF 1.1 권장 1~1.5m). 격자가 이 구간 내내 센서 안에 들어와야 한다.
WORK_Z_MIN_M = 1.0          # spec
WORK_Z_MAX_M = 1.5          # spec
EDGE_MARGIN_PX = 50.0       # design 센서 가장자리 여유

# 레이저 축 수렴각 — 격자를 센서 안에 담기 위한 설계값.
#
# 격자의 이미지상 위치는  u = f·tan(α) − f·b/Z + c_x  이다. 기선 b 때문에
# 격자 전체가 거리에 따라 왼쪽으로 밀리며, 그 양 f·b/Z 는 1.0m 에서
# 522px(센서 폭의 21%)에 이른다. 레이저 축을 카메라와 평행하게 두면
# 이 이동량만큼 센서 한쪽이 통째로 낭비되어, 21선을 담을 수 있는 발산각이
# 21.24°(1.2m 투사 450mm)로 줄어든다.
#
# 레이저를 카메라 쪽으로 조금 기울이면 격자가 작업거리에서 화면 중앙에
# 오므로 양쪽을 고르게 쓸 수 있다. 삼각측량 기하는 그대로이고 발사각의
# 기준축만 바뀌므로, α_i 에 이 각을 더해 쓰면 된다.
#
# 참고: PDF 2.2 의 "120cm 에서 936x936mm" 는 발산각 42.61° 에 해당하는데,
# 12mm 렌즈의 HFOV 38.77° 보다 넓어 그대로는 담기지 않는다. 936mm 를
# 유지하려면 렌즈를 10.4mm 이하로 낮춰야 한다.
LASER_TILT_DEG = 5.1        # design 수렴각 (카메라 쪽으로)
FOV_DEG = 31.0              # design 21선이 1.0~1.5m 내내 센서 안에 드는 최대값

# 선검출 정밀도 (불확실도 산정용)
SIGMA_U_PX = 0.2            # assumed 서브픽셀 반복성. 실장비 측정 필요
TARGET_SIGMA_MM = 2.0       # spec  평활도 목표 정밀도 (PDF 1.1)


# =====================================================================
# 사양에서 유도되는 값
# =====================================================================
def focal_px(focal_mm=LENS_FOCAL_MM, pitch_um=PIXEL_PITCH_UM):
    """
    렌즈 초점거리와 화소 피치에서 픽셀 단위 초점거리를 구한다.

        f_px = f_mm / pixel_pitch_mm

    삼각측량식의 f 는 픽셀 단위여야 한다. 같은 렌즈라도 센서 화소가
    작을수록 f_px 는 커지고, 그만큼 깊이 분해능이 좋아진다.
    """
    return focal_mm / (pitch_um / 1000.0)


def projection_mm_at(z_m, fov_deg=None):
    """거리 z_m 에서 격자가 덮는 폭 [mm]"""
    fov = np.radians(FOV_DEG if fov_deg is None else fov_deg)
    return 2.0 * z_m * 1000.0 * np.tan(fov / 2.0)


F_PX = focal_px()                      # 3478.3 px  (12mm / 3.45µm)
CX_PX = IMAGE_W / 2.0                  # assumed 센서 정중앙. 캘리브레이션 필요
CY_PX = IMAGE_H / 2.0                  # assumed 동일

CAMERA_PARAMS = {
    "f_px":  round(F_PX, 1),
    "b_m":   BASELINE_M,
    "cx_px": CX_PX,
    "cy_px": CY_PX,
    "resolution": [IMAGE_W, IMAGE_H],
}

GRID_PARAMS = {
    "n_vertical":       N_VERTICAL,
    "n_horizontal":     N_HORIZONTAL,
    "fov_deg":          FOV_DEG,
    "laser_tilt_deg":   LASER_TILT_DEG,
    "samples_per_line": 250,
}

def make_line_angles(n_v=None, n_h=None, fov_deg=None, laser_tilt_deg=None):
    """
    V선·H선의 발사각을 만든다. 카메라 좌표계 기준이다.

    수렴각 δ 는 α 에 그대로 더한다. 레이저를 Y축으로 δ 만큼 돌리면 광선
    (tanα₀, tanβ₀, 1) 의 수평 성분이 정확히 tan(α₀+δ) 가 되기 때문이다
    (탄젠트 덧셈정리).

    한계 — β 의 결합
      같은 회전에서 tanβ 는 1/(cosδ − sinδ·tanα₀) 배로 살짝 늘어난다.
      즉 실제 격자는 미세한 사다리꼴이며, 발산각 31°·δ=5.1° 에서 가장자리
      기준 약 ±2.5% 다. 깊이 Z 는 α 와 u 로만 정해지므로 영향이 없고,
      H선 예측 위치에만 최대 24px 반영된다. 실장비에서는 캘리브레이션이
      이 결합을 그대로 측정해 담는다.
    """
    n_v = N_VERTICAL if n_v is None else n_v
    n_h = N_HORIZONTAL if n_h is None else n_h
    fov = np.radians(FOV_DEG if fov_deg is None else fov_deg)
    tilt = np.radians(LASER_TILT_DEG if laser_tilt_deg is None else laser_tilt_deg)
    a = {}
    for i, ang in enumerate(np.linspace(-fov / 2, fov / 2, n_v) + tilt):
        a[f"V{i}"] = {"fixed": "alpha", "angle_rad": float(ang)}
    for j, ang in enumerate(np.linspace(-fov / 2, fov / 2, n_h)):
        a[f"H{j}"] = {"fixed": "beta", "angle_rad": float(ang)}
    return a


def predicted_u(alpha_rad, z_m, camera_params=None):
    """
    발사각 α 의 V선이 거리 z_m 에서 이미지의 어디에 맺히는지.

        u = f·tan(α) − f·b/Z + c_x

    두 번째 항이 기선 때문에 생기는 시차 이동이다. 이 항을 빼먹으면
    예측 위치가 1.2m 에서 435px 어긋나, 추적 밴드(20~50px) 밖으로 나간다.
    """
    cp = camera_params or CAMERA_PARAMS
    return cp["f_px"] * np.tan(alpha_rad) - cp["f_px"] * cp["b_m"] / z_m + cp["cx_px"]


# 값의 출처 등급 — 문서·보고서가 이 표를 그대로 쓴다.
PROVENANCE = {
    "f_px":   ("spec",    "렌즈 12mm ÷ 화소 3.45µm 에서 유도"),
    "b_m":    ("design",  "용역서 고정. 조립 후 실측 필요"),
    "cx_px":  ("assumed", "센서 정중앙 가정. 체커보드 캘리브레이션 필요"),
    "cy_px":  ("assumed", "센서 정중앙 가정. 체커보드 캘리브레이션 필요"),
    "fov_deg": ("design", "21선이 1.0~1.5m 내내 센서 안에 드는 최대값"),
    "tilt":    ("design", "레이저 축 수렴각. 시차 이동량을 상쇄한다"),
    "alpha_i": ("assumed", "발산각을 등각도 분할. DOE 실측값으로 대체 필요"),
    "beta_j":  ("assumed", "동일"),
    "R_t":     ("assumed", "R=I, t=(b,0,0). 스테레오 캘리브레이션 필요"),
    "R_ic":    ("assumed", "단위행렬. IMU–카메라 캘리브레이션 필요"),
    "b_a":     ("assumed", "미구현. 가속도계 bias 보정 필요"),
    "sigma_u": ("assumed", "0.2px 가정. 선검출 반복성 측정 필요"),
}


# =====================================================================
# 해상도 환산
# =====================================================================
def scale_to_resolution(width_px, camera_params=None):
    """
    다른 해상도의 이미지에 맞춰 f, c_x, c_y 를 환산한다.

    f_px 는 센서 해상도에 비례한다. 2448px 기준값을 축소된 이미지에
    그대로 쓰면 예측 격자가 화면 밖으로 나가 검출이 통째로 실패한다
    (실측: 471px 이미지에서 21선 중 5선만 화면 안, 평균 332px 오차).
    """
    cp = dict(camera_params or CAMERA_PARAMS)
    k = float(width_px) / float(cp["resolution"][0])
    h = int(round(cp["resolution"][1] * k))
    return {**cp,
            "f_px":  cp["f_px"] * k,
            "cx_px": cp["cx_px"] * k,
            "cy_px": cp["cy_px"] * k,
            "resolution": [int(width_px), h]}


# =====================================================================
# 정합성 검사
# =====================================================================
def check_consistency(camera_params=None, grid_params=None,
                      z_min=None, z_max=None, margin_px=None, verbose=True):
    """
    격자가 작업거리 전 구간에서 센서 안에 들어오는지 확인한다.

    단순히 시야각만 비교해서는 안 된다. 격자의 이미지상 위치는 기선 때문에
    거리에 따라 f·b/Z 만큼 좌우로 이동하며, 1.0m 에서 그 양이 센서 폭의
    21% 에 이른다. 따라서 가장 가까운 거리와 가장 먼 거리 양쪽에서
    확인해야 한다.

    Returns
    -------
    dict — fits, u_range_near, u_range_far, v_range, usable_z_m
    """
    cp = camera_params or CAMERA_PARAMS
    gp = grid_params or GRID_PARAMS
    z0 = WORK_Z_MIN_M if z_min is None else z_min
    z1 = WORK_Z_MAX_M if z_max is None else z_max
    m = EDGE_MARGIN_PX if margin_px is None else margin_px
    W, H = cp["resolution"]
    f, b, cx, cy = cp["f_px"], cp["b_m"], cp["cx_px"], cp["cy_px"]

    ang = make_line_angles(gp["n_vertical"], gp["n_horizontal"],
                           gp["fov_deg"], gp.get("laser_tilt_deg", 0.0))
    al = np.array([ang[f"V{i}"]["angle_rad"] for i in range(gp["n_vertical"])])
    be = np.array([ang[f"H{j}"]["angle_rad"] for j in range(gp["n_horizontal"])])

    u_near = f * np.tan(al) - f * b / z0 + cx
    u_far = f * np.tan(al) - f * b / z1 + cx
    v = f * np.tan(be) + cy

    fits = (u_near.min() >= m and u_far.max() <= W - m
            and v.min() >= m and v.max() <= H - m)

    # 이 설계로 쓸 수 있는 거리 범위 (가장 왼쪽/오른쪽 선 기준)
    lo = f * b / max(cx + f * np.tan(al.min()) - m, 1e-9)
    hi = f * b / max(cx + f * np.tan(al.max()) - (W - m), 1e-9)
    usable = [round(float(lo), 2), round(float(hi), 2) if hi > 0 else None]

    r = {"fits": bool(fits), "margin_px": m,
         "work_z_m": [z0, z1],
         "u_range_near": [round(float(u_near.min()), 1), round(float(u_near.max()), 1)],
         "u_range_far": [round(float(u_far.min()), 1), round(float(u_far.max()), 1)],
         "v_range": [round(float(v.min()), 1), round(float(v.max()), 1)],
         "usable_z_m": usable,
         "projection_mm": {z: round(float(projection_mm_at(z, gp["fov_deg"])), 0)
                           for z in (z0, z1)}}

    if verbose and not fits:
        print(f"  [캘리브레이션 경고] 격자가 센서를 벗어난다")
        print(f"    Z={z0}m  u = {r['u_range_near'][0]} .. {r['u_range_near'][1]}"
              f"   (허용 {m:.0f} .. {W-m:.0f})")
        print(f"    Z={z1}m  u = {r['u_range_far'][0]} .. {r['u_range_far'][1]}")
        print(f"    v = {r['v_range'][0]} .. {r['v_range'][1]}"
              f"   (허용 {m:.0f} .. {H-m:.0f})")
        print(f"    → 발산각을 줄이거나 레이저 수렴각을 조정할 것")
    return r


def sigma_z_mm(z_m, camera_params=None, sigma_u_px=SIGMA_U_PX):
    """σ_Z = σ_u · Z² / (f · b)  [mm]"""
    cp = camera_params or CAMERA_PARAMS
    return sigma_u_px * z_m ** 2 / (cp["f_px"] * cp["b_m"]) * 1000.0


def fov_mm_at(z_m, camera_params=None):
    """거리 z_m 에서 카메라가 담는 시야 (가로, 세로) [mm]"""
    cp = camera_params or CAMERA_PARAMS
    return (2 * z_m * 1000 * cp["cx_px"] / cp["f_px"],
            2 * z_m * 1000 * cp["cy_px"] / cp["f_px"])


def summary():
    """현재 캘리브레이션 값과 출처를 표로 출력한다."""
    lines = ["캘리브레이션 데이터 (B) — 출고 시 1회 측정",
             "-" * 72]
    rows = [
        ("f_px",    f"{CAMERA_PARAMS['f_px']} px", "f",       "f_px"),
        ("주점",     f"{CX_PX:.1f}, {CY_PX:.1f} px", "c_x,c_y", "cx_px"),
        ("기선",     f"{BASELINE_M} m",            "b",       "b_m"),
        ("DOE 발산각", f"{GRID_PARAMS['fov_deg']}°", "—",      "fov_deg"),
        ("레이저 수렴각", f"{LASER_TILT_DEG}°",         "δ",       "tilt"),
        ("V선 발사각", f"등각도 {N_VERTICAL}분할",     "α_i",     "alpha_i"),
        ("H선 발사각", f"등각도 {N_HORIZONTAL}분할",   "β_j",     "beta_j"),
        ("카메라–레이저 자세", "R=I, t=(b,0,0)",     "R, t",    "R_t"),
        ("IMU–카메라 자세", "단위행렬",              "R_ic",    "R_ic"),
        ("가속도계 bias", "미구현",                  "b_a",     "b_a"),
        ("선검출 픽셀오차", f"{SIGMA_U_PX} px",       "σ_u",     "sigma_u"),
    ]
    for name, val, sym, key in rows:
        grade, note = PROVENANCE[key]
        lines.append(f"  {name:<18} {sym:<8} {val:<18} [{grade:<7}] {note}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
    print()
    print("유도값")
    print("-" * 72)
    print(f"  f_px      = {LENS_FOCAL_MM}mm / {PIXEL_PITCH_UM}\u00b5m = {F_PX:.1f} px")
    print(f"  카메라 HFOV {2*np.degrees(np.arctan(CX_PX/F_PX)):.2f}°  "
          f"VFOV {2*np.degrees(np.arctan(CY_PX/F_PX)):.2f}°")
    print(f"  격자 발산각 {FOV_DEG}°  수렴각 {LASER_TILT_DEG}°")
    print()
    print("거리별 시야 · 격자 투사폭 · 깊이 노이즈 (σ_u = 0.2px, b = 150mm)")
    print("-" * 72)
    print(f"  {'거리':<7}{'카메라 시야':<22}{'격자 투사폭':<13}{'mm/px':<9}{'σ_Z':<8}")
    for z in (0.5, 1.0, 1.2, 1.5, 2.0, 3.0):
        w, h = fov_mm_at(z)
        print(f"  {z:<7.1f}{f'{w:.0f} × {h:.0f} mm':<22}"
              f"{f'{projection_mm_at(z):.0f} mm':<13}{w/IMAGE_W:<9.4f}{sigma_z_mm(z):<8.2f}")
    print()
    print("정합성 검사 — 격자가 작업거리 전 구간에서 센서 안에 드는가")
    print("-" * 72)
    r = check_consistency()
    W, H = IMAGE_W, IMAGE_H
    m = EDGE_MARGIN_PX
    print(f"  작업거리 {r['work_z_m'][0]} ~ {r['work_z_m'][1]} m,  마진 {m:.0f}px")
    print(f"    Z={r['work_z_m'][0]}m  u = {r['u_range_near'][0]:7.1f} .. "
          f"{r['u_range_near'][1]:7.1f}   (허용 {m:.0f} .. {W-m:.0f})")
    print(f"    Z={r['work_z_m'][1]}m  u = {r['u_range_far'][0]:7.1f} .. "
          f"{r['u_range_far'][1]:7.1f}")
    print(f"    v = {r['v_range'][0]:7.1f} .. {r['v_range'][1]:7.1f}"
          f"   (허용 {m:.0f} .. {H-m:.0f})")
    print(f"  판정: {'격자 전부 센서 안' if r['fits'] else '벗어남'}")
    print(f"  이 설계로 쓸 수 있는 거리: "
          f"{r['usable_z_m'][0]} ~ {r['usable_z_m'][1]} m")
