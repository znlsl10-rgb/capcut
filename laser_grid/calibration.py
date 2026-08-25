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
DOE_PROJECTION_MM = 936.0   # spec  120cm 에서 약 936×936mm
DOE_REFERENCE_Z_MM = 1200.0 # spec  위 투사폭의 기준 거리

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


def doe_fov_deg(projection_mm=DOE_PROJECTION_MM, z_mm=DOE_REFERENCE_Z_MM):
    """투사폭과 그 기준 거리에서 DOE 전체 발산각을 역산한다."""
    return 2.0 * np.degrees(np.arctan((projection_mm / 2.0) / z_mm))


F_PX = focal_px()                      # 3478.3 px  (12mm / 3.45µm)
CX_PX = IMAGE_W / 2.0                  # assumed 센서 정중앙. 캘리브레이션 필요
CY_PX = IMAGE_H / 2.0                  # assumed 동일
FOV_DEG = doe_fov_deg()                # 42.61°  (936mm @ 1.2m)

# 12mm 렌즈로 21선을 전부 담으려면 필요한 발산각 (마진 50px 기준).
# PDF 의 DOE 사양(42.61°)은 이보다 넓어 양 끝 선이 센서를 벗어난다.
FOV_DEG_FIT_SENSOR = 2.0 * np.degrees(np.arctan((CX_PX - 50.0) / F_PX))

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
    "fov_deg":          round(FOV_DEG, 2),
    "samples_per_line": 250,
}

# 값의 출처 등급 — 문서·보고서가 이 표를 그대로 쓴다.
PROVENANCE = {
    "f_px":   ("spec",    "렌즈 12mm ÷ 화소 3.45µm 에서 유도"),
    "b_m":    ("design",  "용역서 고정. 조립 후 실측 필요"),
    "cx_px":  ("assumed", "센서 정중앙 가정. 체커보드 캘리브레이션 필요"),
    "cy_px":  ("assumed", "센서 정중앙 가정. 체커보드 캘리브레이션 필요"),
    "fov_deg": ("spec",   "DOE 투사폭 936mm @1.2m 에서 역산"),
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
def check_consistency(camera_params=None, grid_params=None, verbose=True):
    """
    격자가 카메라 시야 안에 들어오는지 확인한다.

    PDF 의 카메라 사양(12mm 렌즈)과 DOE 사양(936mm @1.2m)은 서로
    맞지 않는다. 카메라 시야는 1.2m 에서 845mm 인데 DOE 는 936mm 를
    투사하므로, 격자가 시야보다 약 10% 넓어 양 끝 선이 센서를 벗어난다.
    설계에 되먹여야 할 사항이라 조용히 넘기지 않고 보고한다.

    Returns
    -------
    dict — n_lines, n_inside, hfov_deg, fov_deg, u_range, fits
    """
    cp = camera_params or CAMERA_PARAMS
    gp = grid_params or GRID_PARAMS
    f, cx = cp["f_px"], cp["cx_px"]
    W = cp["resolution"][0]
    fov = np.radians(gp["fov_deg"])
    n = gp["n_vertical"]

    u = f * np.tan(np.linspace(-fov / 2, fov / 2, n)) + cx
    inside = int(((u >= 0) & (u < W)).sum())
    hfov = 2 * np.degrees(np.arctan(cx / f))

    r = {"n_lines": n, "n_inside": inside,
         "hfov_deg": round(float(hfov), 2),
         "fov_deg": float(gp["fov_deg"]),
         "u_range": [round(float(u[0]), 1), round(float(u[-1]), 1)],
         "fits": inside == n}

    if verbose and not r["fits"]:
        print(f"  [캘리브레이션 경고] DOE 발산각 {r['fov_deg']}° > "
              f"카메라 HFOV {r['hfov_deg']}°")
        print(f"    V선 {n}개 중 {inside}개만 센서 안 "
              f"(예측 u = {r['u_range'][0]} .. {r['u_range'][1]} px, 폭 {W})")
        print(f"    → 격자가 시야보다 {r['fov_deg']/r['hfov_deg']:.1%} 넓다. "
              f"양 끝 선은 촬영되지 않는다")
        print(f"    해소안 ① DOE 발산각을 {FOV_DEG_FIT_SENSOR:.2f}° 이하로 "
              f"(1.2m 투사 "
              f"{2*1200*np.tan(np.radians(FOV_DEG_FIT_SENSOR/2)):.0f}mm)")
        print(f"    해소안 ② 렌즈를 "
              f"{(cx-50)/np.tan(np.radians(r['fov_deg']/2))*PIXEL_PITCH_UM/1e3:.2f}mm "
              f"이하로 (936mm 전부 수용)")
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
    print(f"  f_px      = {LENS_FOCAL_MM}mm / {PIXEL_PITCH_UM}µm = {F_PX:.1f} px")
    print(f"  카메라 HFOV {2*np.degrees(np.arctan(CX_PX/F_PX)):.2f}°  "
          f"VFOV {2*np.degrees(np.arctan(CY_PX/F_PX)):.2f}°")
    print(f"  DOE 발산각 = 2·atan({DOE_PROJECTION_MM/2:.0f}/{DOE_REFERENCE_Z_MM:.0f})"
          f" = {FOV_DEG:.2f}°")
    print()
    print("거리별 시야 · 깊이 노이즈 (σ_u = 0.2px, b = 150mm)")
    print("-" * 72)
    print(f"  {'거리':<8}{'시야 (가로×세로)':<26}{'mm/px':<10}{'σ_Z':<10}")
    for z in (0.5, 1.0, 1.2, 1.5, 2.0, 3.0):
        w, h = fov_mm_at(z)
        print(f"  {z:<8.1f}{f'{w:.0f} × {h:.0f} mm':<26}"
              f"{w/IMAGE_W:<10.4f}{sigma_z_mm(z):<10.2f}")
    print()
    print("정합성 검사")
    print("-" * 72)
    r = check_consistency()
    if r["fits"]:
        print(f"  V선 {r['n_lines']}개 전부 센서 안. 이상 없음")
