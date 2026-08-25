#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_capture.py — Isaac raycast 내보내기 폴더를 검측 입력으로
========================================================================
한 폴더에 아래가 들어 있는 형식을 읽는다.

  camera_params.json   f_px·주점·기선·격자·rig_transform·screenshot_size
  cast_pixels.json     {선ID: {fixed, angle_deg, points:[{uv, alpha_deg,
                       beta_deg, xyz_world}, ...]}}
  CAM.png / CAST.png   화면 캡처 (선택 — 결과 이미지 배경으로만 쓴다)

두 가지를 데이터에서 직접 복원한다. 헤더 값을 그대로 믿으면 틀린다.

1) 해상도
   uv 는 screenshot_size(1269×1063) 기준인데 f_px·주점은 sensor_size
   (2448×2048) 기준이다. 그대로 쓰면 삼각측량이 통째로 어긋난다.
   실제로 동봉된 xyz_result.json 이 이 상태에서 만들어져 벽까지 거리가
   1.5m 대신 16m 로 나와 있다. uv 를 센서 단위로 올려 맞춘다. uv 가
   정수가 아니라 해석적 실수값이라 이 환산으로 잃는 정보는 없다.

2) 카메라 자세
   camera_forward_world 만 있고 롤(광축 둘레 회전)이 없다. 아래를 보는
   촬영에서는 forward 와 월드 up 이 거의 나란해져 롤을 세울 수가 없다.
   게다가 캡처마다 uv 축 방향이 다르다(이 표본에서 벽체는 180° 돌아
   있고 동바리는 그렇지 않다). 그래서 자세를 헤더에서 만들지 않고
   (xyz_world, uv) 대응에서 Kabsch 로 맞춘다. 어떤 규약으로 내보냈든
   데이터 자신과 일치하는 자세가 나온다.

H선을 쓰지 않는 이유
   내보내기에는 H선 점에도 alpha_deg 가 들어 있다. 그러나 실장비는
   H선 위 임의 점의 α 를 알 수 없다(V×H 교점에서만 회복된다). 그것을
   쓰면 시뮬레이션에서만 되는 검증이 되므로 V선만 쓴다.

실행:
  python3 load_capture.py <폴더> [--pitch 자동] [--out 출력폴더]
  python3 load_capture.py <상위폴더> --all
========================================================================
"""
import argparse, json, os
import numpy as np
import importlib.util as _ilu


def _load(name):
    spec = _ilu.spec_from_file_location(
        name, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           f"{name}.py"))
    m = _ilu.module_from_spec(spec); spec.loader.exec_module(m)
    return m


CALIB = _load("calibration")
PIPE = _load("pipeline_region")
DETECT = _load("A_선검출")

# 검출선과 정답선을 같은 선으로 볼 최대 거리 [px].
# 이 사양의 격자 간격은 화면에서 45~55px 이므로, 5px 이면 이웃 선과
# 혼동될 여지 없이 "찾았다/못 찾았다" 를 가른다.
MATCH_TOL_PX = 5.0
REPORT = _load("report")
XLS = _load("report_excel")


# =====================================================================
# 자세 복원
# =====================================================================
def fit_camera_rotation(P_world, uv, cam_pos, f, cx, cy):
    """
    (월드 3D 점, 화소 좌표) 대응에서 카메라 회전을 맞춘다.

    카메라 위치는 이미 알고 있으므로 남은 미지수는 회전뿐이다. 각 점의
    월드 방향 단위벡터와 화소가 가리키는 카메라 좌표계 단위벡터를
    맞추는 직교 프로크루스테스 문제이고, SVD 로 닫힌 해가 나온다.

        d_i = normalize(u−c_x, v−c_y, f)      카메라 좌표계 시선
        w_i = normalize(P_i − C)              월드 시선
        R  = argmin Σ |R·d_i − w_i|²

    반사(det<0)는 회전이 아니므로 마지막 특이벡터를 뒤집어 막는다.
    """
    d = np.stack([uv[:, 0] - cx, uv[:, 1] - cy, np.full(len(uv), f)], axis=1)
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    w = P_world - np.asarray(cam_pos, float)
    w /= np.linalg.norm(w, axis=1, keepdims=True)
    U, _, Vt = np.linalg.svd(w.T @ d)
    S = np.eye(3)
    S[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ S @ Vt                       # 카메라→월드
    resid = np.degrees(np.arccos(np.clip(
        np.einsum("ij,ij->i", (R @ d.T).T, w), -1, 1)))
    return R, float(np.median(resid))


# =====================================================================
# 폴더 읽기
# =====================================================================
def load_folder(path, world_up=(0.0, 0.0, 1.0), stride=1):
    """
    내보내기 폴더 하나를 검측 입력 묶음으로 바꾼다.

    Returns
    -------
    dict — lines_pixels, line_angles, camera_params, g_hat, diag, meta
    """
    cp_raw = json.load(open(os.path.join(path, "camera_params.json"),
                            encoding="utf-8"))
    cast = json.load(open(os.path.join(path, "cast_pixels.json"),
                          encoding="utf-8"))

    SW, SH = cp_raw["sensor_size"]
    sw, sh = cp_raw.get("screenshot_size", [SW, SH])
    su, sv = SW / float(sw), SH / float(sh)      # 화면→센서 (가로·세로 따로)
    f = float(cp_raw["camera"]["f_px"])
    cx = float(cp_raw["camera"]["cx_px"])
    cy = float(cp_raw["camera"]["cy_px"])
    b = float(cp_raw["baseline_m"])

    # ── V선만 모은다 (위 주석 참조) ──
    lines_pixels, line_angles, P_all, uv_all = {}, {}, [], []
    n_h = 0
    for lid, ln in cast.items():
        pts = ln["points"][::stride]
        uv = np.array([[p["uv"][0] * su, p["uv"][1] * sv] for p in pts])
        P = np.array([p["xyz_world"] for p in pts], float)
        P_all.append(P); uv_all.append(uv)          # 자세 적합엔 V·H 모두 쓴다
        if ln["fixed"] != "alpha":
            n_h += 1
            continue
        lines_pixels[lid] = uv
        line_angles[lid] = {"fixed": "alpha",
                            "angle_rad": float(np.radians(ln["angle_deg"]))}
    P_all = np.concatenate(P_all); uv_all = np.concatenate(uv_all)

    rt = cp_raw.get("rig_transform") or {}
    C = np.array(rt["camera_pos_world"], float)
    L = np.array(rt["laser_pos_world"], float)
    R, resid_deg = fit_camera_rotation(P_all, uv_all, C, f, cx, cy)

    # 기선 방향 확인 — eq1 은 카메라가 조사기의 +x 쪽에 있다고 본다.
    t_cam = (C - L) @ R                  # 조사기→카메라, 카메라 좌표계
    flipped = False
    if t_cam[0] < 0:
        # 내보내기가 180° 돌아 있다. 화소를 주점 기준으로 뒤집고 자세의
        # x·y 축도 같이 뒤집어 규약을 되돌린다(광축 둘레 180° 회전).
        flipped = True
        for lid in lines_pixels:
            lines_pixels[lid] = np.stack(
                [2 * cx - lines_pixels[lid][:, 0],
                 2 * cy - lines_pixels[lid][:, 1]], axis=1)
        R = R @ np.diag([-1.0, -1.0, 1.0])
        t_cam = (C - L) @ R

    g_hat = np.array(world_up, float) * -1.0 @ R    # 조사기 좌표계 중력
    g_hat /= np.linalg.norm(g_hat)

    camera_params = {"f_px": f, "b_m": b, "cx_px": cx, "cy_px": cy,
                     "resolution": [SW, SH]}
    diag = {
        "화면→센서 배율": (round(su, 4), round(sv, 4)),
        "자세 적합 잔차(°)": round(resid_deg, 4),
        "uv 180° 뒤집힘": flipped,
        "기선 벡터(카메라좌표, m)": [round(x, 4) for x in t_cam],
        "기선 x성분 대비 잔여(mm)": round(
            float(np.hypot(t_cam[1], t_cam[2])) * 1000, 1),
        "V선 수": len(lines_pixels), "H선 수": n_h,
        "V선 점 수": int(sum(len(v) for v in lines_pixels.values())),
        "중력(조사기좌표)": [round(x, 4) for x in g_hat],
        "장비 하향각(°)": round(float(np.degrees(np.arctan2(
            g_hat[2], g_hat[1]))), 2),
    }
    meta = {"case": cp_raw.get("case_name"),
            "captured_at": cp_raw.get("captured_at"),
            "grid": cp_raw.get("grid"), "sensor": [SW, SH],
            "screenshot": [sw, sh]}
    return {"lines_pixels": lines_pixels, "line_angles": line_angles,
            "camera_params": camera_params, "g_hat": g_hat, "R_cam": R,
            "diag": diag, "meta": meta, "raw": cp_raw, "cast": cast}


# =====================================================================
# 선검출 정확도 — 화소 단계가 맞아야 3D 가 맞는다
# =====================================================================
def _flip_about_principal(im, cx, cy, resample=None):
    """
    주점 (cx, cy) 를 중심으로 이미지를 180° 돌린다.

    PIL 의 ROTATE_180 은 u → (w−1) − u 로 **이미지 중심** 기준이다.
    화소 좌표는 주점 기준으로 2·c − u 로 되돌리므로, 주점이 이미지
    중심과 다르면 그만큼 어긋난다. 이 표본에서는 폭 1269, 주점 634.5 라
    정확히 1px 차이가 났고, 그것이 벽체 캡처의 u 오차 중앙값 −0.96px 로
    그대로 나타났다. 센서 환산 1px 은 1.5m 에서 깊이 10mm 다.
    """
    from PIL import Image
    if resample is None:
        resample = Image.BICUBIC
    # AFFINE 은 출력(x,y) → 입력(ax+by+c, dx+ey+f) 로 역방향 사상이다.
    return im.transform(im.size, Image.AFFINE,
                        (-1, 0, 2.0 * cx, 0, -1, 2.0 * cy), resample=resample)


def evaluate_line_detection(path, cap, image_name="CAST.png"):
    """
    렌더 이미지에 A_선검출 을 돌려 raycast 정답 화소와 대조한다.

    왜 재야 하는가
    -------------
    삼각측량은 Z = f·b / (f·tanα − (u − c_x)) 다. 분모가 화소 차이라,
    u 가 흔들린 만큼 그대로 깊이가 흔들린다. 민감도는

        dZ = Z² / (f·b) · du

    이고 이 장비의 legacy 사양(f=1593px, b=150mm)에서는 2.7m 거리에서
    1px 이 12mm 다. 즉 뒤쪽 검측식이 아무리 정확해도 화소 단계에서
    1px 이 틀리면 그 자리에서 끝난다.

    무엇과 대조하나
    --------------
    이 내보내기에는 cast_pixels.json 에 raycast 로 구한 정답 화소가 들어
    있다. 같은 장면의 렌더 이미지(CAST.png)에 선검출을 돌리면 검출값과
    정답을 직접 뺄 수 있다. 검측 파이프라인은 정답 화소를 그대로 썼으므로
    이 비교가 곧 "실장비에서 무엇이 더 나빠지는가" 를 보여준다.

    비교 방법
    --------
    V선은 행(v)을 따라가며 u 를 본다. 정답과 검출의 샘플 밀도가 다르므로
    인덱스로 맞추지 않고, 정답을 검출점의 v 위치에 선형보간해 재추출한 뒤
    같은 v 에서 u 차이를 잰다.
    """
    cast = cap["cast"]
    cp_raw = cap["raw"]
    fp = os.path.join(path, image_name)
    if not os.path.exists(fp):
        return None
    try:
        from PIL import Image
    except ImportError:
        return None

    im = Image.open(fp).convert("RGB")
    w, h = im.size
    SW, SH = cp_raw["sensor_size"]
    su, sv = SW / float(w), SH / float(h)
    f_img = float(cp_raw["camera"]["f_px"]) / su
    cx_img = float(cp_raw["camera"]["cx_px"]) / su
    cy_img = float(cp_raw["camera"]["cy_px"]) / sv
    flipped = bool(cap["diag"]["uv 180° 뒤집힘"])
    if flipped:
        im = _flip_about_principal(im, cx_img, cy_img)
    img = np.asarray(im)
    b = float(cp_raw["baseline_m"])
    grid = cp_raw.get("grid") or {}
    z_ref = _median_depth(cap)

    cp = {"f_px": f_img, "b_m": b, "cx_px": cx_img, "cy_px": cy_img,
          "resolution": [w, h], "image_w": w, "image_h": h,
          "n_v": grid.get("n_vertical", 21), "n_h": grid.get("n_horizontal", 21),
          "fov_h_deg": grid.get("fov_deg"), "fov_v_deg": grid.get("fov_deg"),
          "standoff_z": z_ref}
    line_angles = {lid: {"fixed": ln["fixed"],
                         "angle_rad": float(np.radians(ln["angle_deg"]))}
                   for lid, ln in cast.items()}
    try:
        det = DETECT.detect(img, {}, line_angles, cp, multi_surface=True)
    except Exception as e:
        return {"error": f"선검출 실패: {e}"}

    # ── 검출선 ↔ 정답선을 **위치로** 짝짓는다 ──
    # ID 로 짝지으면 안 된다. 이 내보내기는 H선 번호가 코드와 반대로
    # 매겨져 있어(정답 H0 이 화면 아래, 코드 H0 이 화면 위) ID 로 빼면
    # 970px 짜리 오차가 나온다. 실제로 알고 싶은 것은 "선을 찾았는가,
    # 얼마나 정확한가" 이므로 위치로 짝짓고, 번호가 맞는지는 따로 센다.
    def _key(arr, fixed):
        return float(np.median(arr[:, 0 if fixed == "alpha" else 1]))

    det_info = {}
    for lid, pts in det.items():
        d = np.array(pts, float)
        if len(d) >= 3:
            det_info[lid] = (d, _key(d, "alpha" if lid.startswith("V") else "beta"))

    rows, all_err = [], []
    n_id_ok = {"V": 0, "H": 0}
    n_id_tot = {"V": 0, "H": 0}
    for lid, ln in sorted(cast.items(),
                          key=lambda kv: (kv[0][0], int(kv[0][1:]))):
        gt = np.array([[p["uv"][0], p["uv"][1]] for p in ln["points"]], float)
        if flipped:
            gt = np.stack([2 * cx_img - gt[:, 0], 2 * cy_img - gt[:, 1]], axis=1)
        z_line = float(np.median([_depth_of(p, cap) for p in ln["points"][::200]]))
        axis = lid[0]
        n_id_tot[axis] += 1
        g_key = _key(gt, ln["fixed"])

        # 같은 방향의 검출선 중 가장 가까운 것
        cand = [(abs(k - g_key), l, d) for l, (d, k) in det_info.items()
                if l[0] == axis]
        row = {"lid": lid, "fixed": ln["fixed"], "n_gt": len(gt),
               "z_m": round(z_line, 3), "gt_pos": round(g_key, 1)}
        if not cand:
            row.update(n_det=0, matched=None, err_med=None, err_rms=None,
                       err_p95=None, err_max=None, id_ok=False,
                       note="검출선 없음")
            rows.append(row); continue
        gap, mlid, d = min(cand, key=lambda t: t[0])
        row["matched"] = mlid
        row["match_gap_px"] = round(gap, 2)
        row["id_ok"] = (mlid == lid)
        if row["id_ok"]:
            n_id_ok[axis] += 1
        if gap > MATCH_TOL_PX:
            row.update(n_det=0, err_med=None, err_rms=None, err_p95=None,
                       err_max=None,
                       note=f"미검출 — 가장 가까운 검출선이 {gap:.1f}px 떨어져 있음")
            rows.append(row); continue

        row["n_det"] = len(d)
        if ln["fixed"] == "alpha":          # V선: v 를 따라가며 u 오차
            o = np.argsort(gt[:, 1])
            ref = np.interp(d[:, 1], gt[o, 1], gt[o, 0])
            e = d[:, 0] - ref
        else:                                # H선: u 를 따라가며 v 오차
            o = np.argsort(gt[:, 0])
            ref = np.interp(d[:, 0], gt[o, 0], gt[o, 1])
            e = d[:, 1] - ref
        # 계통 편차와 무작위 오차를 갈라 놓는다. 둘은 성질도 대책도 다르다.
        #   계통(중앙값) — 좌표 규약·주점·기선 같은 것이 어긋난 것. 소프트웨어로 고친다.
        #   무작위(중앙값 둘레 표준편차) — 이것이 진짜 검출 정밀도 σ_u 다.
        row.update(err_med=float(np.median(e)),
                   err_noise=float(np.std(e - np.median(e))),
                   err_rms=float(np.sqrt(np.mean(e ** 2))),
                   err_p95=float(np.percentile(np.abs(e), 95)),
                   err_max=float(np.abs(e).max()), note=None)
        rows.append(row)
        if ln["fixed"] == "alpha":
            all_err.append(e)

    E = np.concatenate(all_err) if all_err else np.zeros(0)
    v_rows = [r for r in rows if r["fixed"] == "alpha"]
    ok = [r for r in v_rows if r["err_rms"] is not None]
    missed = [r for r in v_rows if r["err_rms"] is None]

    # 화소 오차를 깊이 오차로 환산 — 이 숫자가 최종 정확도를 좌우한다.
    #   dZ = Z²/(f·b) · du       (센서 화소 기준)
    f_sensor = float(cp_raw["camera"]["f_px"])
    bias = float(np.median(E)) if len(E) else None
    noise = float(np.std(E - np.median(E))) if len(E) else None
    rms_sensor = (float(np.sqrt(np.mean(E ** 2))) * su) if len(E) else None
    to_mm = (lambda px: z_ref ** 2 / (f_sensor * b) * (px * su) * 1000.0)
    dz_mm = to_mm(float(np.sqrt(np.mean(E ** 2)))) if len(E) else None
    return {
        "image": image_name, "image_size": [w, h], "flipped": flipped,
        "scale_to_sensor": round(su, 4),
        "f_px_image": round(f_img, 1), "f_px_sensor": f_sensor,
        "z_ref_m": round(z_ref, 3),
        "n_lines_gt": len(cast), "n_lines_det": len(det),
        "rows": rows,
        "err_med_px": (round(float(np.median(E)), 4) if len(E) else None),
        "err_rms_px": (round(float(np.sqrt(np.mean(E ** 2))), 4) if len(E) else None),
        "err_p95_px": (round(float(np.percentile(np.abs(E), 95)), 3) if len(E) else None),
        "err_bias_px": (round(bias, 4) if bias is not None else None),
        "err_noise_px": (round(noise, 4) if noise is not None else None),
        "err_rms_sensor_px": (round(rms_sensor, 4) if rms_sensor is not None else None),
        "bias_sensor_px": (round(bias * su, 4) if bias is not None else None),
        "noise_sensor_px": (round(noise * su, 4) if noise is not None else None),
        "depth_err_mm": (round(dz_mm, 3) if dz_mm is not None else None),
        "depth_bias_mm": (round(to_mm(abs(bias)), 3) if bias is not None else None),
        "depth_noise_mm": (round(to_mm(noise), 3) if noise is not None else None),
        "mm_per_px_depth": round(z_ref ** 2 / (f_sensor * b) * su * 1000.0, 3),
        "n_v_matched": len(ok), "n_v_total": len(v_rows),
        "n_v_missed": len(missed),
        "missed_lines": [r["lid"] for r in missed],
        "id_ok": {k: (n_id_ok[k], n_id_tot[k]) for k in ("V", "H")},
        "sigma_u_design_px": CALIB.SIGMA_U_PX,
    }


def _depth_of(point, cap):
    """raycast 점의 조사기 좌표 Z."""
    rt = cap["raw"]["rig_transform"]
    L = np.array(rt["laser_pos_world"], float)
    R = cap["R_cam"]
    return float((np.array(point["xyz_world"], float) - L) @ R[:, 2])


def _median_depth(cap):
    """장면 대표 거리 — 선검출 예측 밴드의 시차항에 쓰인다."""
    zs = []
    for lid, ln in cap["cast"].items():
        if ln["fixed"] != "alpha":
            continue
        zs.append(_depth_of(ln["points"][len(ln["points"]) // 2], cap))
    return float(np.median(zs)) if zs else 1.2


def _base_image(path, size, flipped=False, cx_img=None, cy_img=None):
    """
    결과 이미지의 배경을 만든다 — 장면 사진 + **실제** 레이저선.

    이 내보내기에는 그림이 둘 있고 격자가 서로 다르다.

      CAM.png    장면 사진 위에 격자를 얹은 것. 그런데 그 격자는 화면을
                 등간격으로 나눠 그린 것이다(실측 간격 47.2~48.1px,
                 최대/최소 1.023).
      CAST.png   레이저만 렌더한 것. 간격이 44~57px 로 바깥이 넓다
                 (최대/최소 1.296). u = f·tan α 를 그대로 따르며
                 cast_pixels.json 의 정답 화소와 0.5px 안에서 일치한다.

    삼각측량이 쓰는 것은 발사각이므로 물리적으로 맞는 쪽은 CAST 다.
    CAM 의 격자를 배경으로 깔면 검출점이 그 위에 얹히지 않는데, 이는
    검출이 틀려서가 아니라 배경 격자가 발사각을 반영하지 않아서다.

    그래서 CAM 에서 격자만 지우고(초록 과잉 화소의 G 를 R·B 평균으로
    되돌린다) 그 자리에 CAST 의 실제 레이저를 얹는다. 장면은 그대로
    보이면서 검출점이 실제 레이저 위에 놓인다.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    def _load_png(name):
        fp = os.path.join(path, name)
        if not os.path.exists(fp):
            return None
        im = Image.open(fp).convert("RGB")
        if flipped:
            cx = cx_img if cx_img is not None else im.size[0] / 2.0
            cy = cy_img if cy_img is not None else im.size[1] / 2.0
            im = _flip_about_principal(im, cx, cy)
        return np.asarray(im.resize((size[0], size[1]), Image.BICUBIC), float)

    scene = _load_png("CAM.png")
    laser = _load_png("CAST.png")
    if scene is None:
        return None if laser is None else laser.astype(np.uint8)

    # CAM 의 등간격 격자 제거 — 초록 과잉분만 눌러 표면색을 되살린다
    rb = 0.5 * (scene[:, :, 0] + scene[:, :, 2])
    over = scene[:, :, 1] - rb
    m = over > 25
    scene[m, 1] = rb[m]

    if laser is not None:
        # CAST 의 실제 레이저를 초록으로 얹는다
        lg = laser[:, :, 1] - 0.5 * (laser[:, :, 0] + laser[:, :, 2])
        a = np.clip(lg / 180.0, 0.0, 1.0)[:, :, None]
        tint = np.array([70.0, 245.0, 110.0])
        scene = scene * (1 - a) + tint * a
    return np.clip(scene, 0, 255).astype(np.uint8)


# =====================================================================
# 검측 실행
# =====================================================================
def inspect_folder(path, out_dir=None, backend="geom", stride=1, site=None,
                   sigma_u_px=None, eval_detection=True):
    name = os.path.basename(os.path.normpath(path))
    cap = load_folder(path, stride=stride)
    cp = cap["camera_params"]

    print("=" * 70)
    print(f"입력: {name}   ({cap['meta'].get('case')})")
    print("=" * 70)
    for k, v in cap["diag"].items():
        print(f"  {k:<24}{v}")

    lines_xyz, lines_uv, skipped = PIPE.triangulate_lines(
        cap["lines_pixels"], cap["line_angles"], cp)
    n3d = sum(len(v) for v in lines_xyz.values())
    print(f"  {'삼각측량 성공 점':<24}{n3d}")
    if n3d == 0:
        print("  [중단] 삼각측량된 점이 없다.")
        return None

    # 라캐스트 참값과 대조 — 이 내보내기에는 xyz_world 가 있으므로
    # 검측 이전 단계(해상도·자세·기선)가 맞았는지 여기서 확인할 수 있다.
    zt = _truth_depth(cap, lines_xyz)
    if zt is not None:
        print(f"  {'깊이 복원오차(중앙값)':<24}{zt*1000:.3f} mm  ← raycast 참값 대조")

    out_dir = out_dir or os.path.join(path, "_검측결과")
    os.makedirs(out_dir, exist_ok=True)

    su = CALIB.SIGMA_U_PX if sigma_u_px is None else float(sigma_u_px)
    # ── 선검출 정확도 ──
    # 검측 파이프라인은 정답 화소를 그대로 썼다. 실장비는 이미지에서
    # 화소를 찾아내야 하므로, 그 단계가 얼마나 정확한지 따로 잰다.
    # 화소 1px 이 깊이 몇 mm 인지까지 환산해 조서에 남긴다.
    det_eval = None
    if eval_detection:
        try:
            det_eval = evaluate_line_detection(path, cap)
        except Exception as e:
            det_eval = {"error": f"평가 실패: {e}"}
        if det_eval and not det_eval.get("error"):
            print(f"\n  선검출 대조 ({det_eval['image']}) — 정답 화소 기준")
            print(f"    V선 검출        {det_eval['n_v_matched']}/{det_eval['n_v_total']}"
                  + (f"   미검출 {det_eval['missed_lines']}"
                     if det_eval["missed_lines"] else ""))
            print(f"    계통 편차        {det_eval['err_bias_px']:+.3f} px  "
                  f"→ 깊이 {det_eval['depth_bias_mm']:.1f} mm")
            print(f"    무작위 오차 σ_u   {det_eval['err_noise_px']:.3f} px  "
                  f"→ 깊이 {det_eval['depth_noise_mm']:.1f} mm  "
                  f"(설계 가정 {det_eval['sigma_u_design_px']} px)")

    res = PIPE.inspect_image(lines_uv, lines_xyz, cp, cap["g_hat"],
                             seg_backend=backend, sigma_u_px=su)
    print()
    print(PIPE.format_report(res))

    sc_u = cp["resolution"][0] / float(cap["meta"]["screenshot"][0])
    sc_v = cp["resolution"][1] / float(cap["meta"]["screenshot"][1])
    base = _base_image(path, cp["resolution"],
                       flipped=bool(cap["diag"]["uv 180° 뒤집힘"]),
                       cx_img=cp["cx_px"] / sc_u, cy_img=cp["cy_px"] / sc_v)
    seg = REPORT.save_segmentation(os.path.join(out_dir, f"{name}_세그멘테이션.png"),
                                   res, base_image=base,
                                   shape=(cp["resolution"][1], cp["resolution"][0]))
    meta = {"현장": site or "-", "입력 폴더": name,
            "케이스": cap["meta"].get("case"),
            "촬영 시각": cap["meta"].get("captured_at")}
    meta.update({k: str(v) for k, v in cap["diag"].items()})
    caveats = [
        "실촬영이 아니라 Isaac raycast 내보내기다. 선검출(A_선검출) 단계를 "
        "거치지 않았으므로 검출 오차는 0 이고, 검측식·영역분할만 검증된다.",
        f"불확실도(σ_n)는 선검출 오차 σ_u={su}px 를 가정해 계산한 값이다. "
        f"이 내보내기의 uv 는 해석적 raycast 값이라 실제 검출 오차가 0 이므로, "
        f"표에 적힌 σ_n 은 측정치가 아니라 설계 가정에 따른 예상치다.",
        "카메라 자세는 헤더가 아니라 (xyz_world, uv) 대응에서 Kabsch 로 "
        "복원했다. 헤더에는 롤이 없어 아래를 보는 촬영에서 자세를 세울 수 "
        "없고, 캡처마다 uv 축 방향도 다르다.",
    ]
    if backend == "geom":
        caveats.append("기하 전용 백엔드는 동바리/기둥/철근과 벽/거푸집/조적을 "
                       "구분하지 못한다. 부재 종류는 사람이 확인해야 한다.")
    if det_eval and not det_eval.get("error"):
        if det_eval["missed_lines"]:
            caveats.append(
                f"선검출이 {len(det_eval['missed_lines'])}개 선을 놓쳤다"
                f"({', '.join(det_eval['missed_lines'])}). 이 표본에서는 앞에 선"
                f" 부재 위에 떨어진 선들이며, 예측 밴드를 장면 대표거리 하나로"
                f" 잡는 한 다른 깊이의 면에 걸린 선은 놓치기 쉽다.")
        if abs(det_eval["err_bias_px"]) > 0.3:
            caveats.append(
                f"선검출에 {det_eval['err_bias_px']:+.2f}px 의 계통 편차가 있다"
                f"(깊이 {det_eval['depth_bias_mm']:.1f}mm). 무작위 오차가 아니라"
                f" 좌표 규약이 어긋난 것이므로 원인을 찾아 제거해야 한다.")
    xl = XLS.save_excel(os.path.join(out_dir, f"{name}_품질검측조서.xlsx"), res,
                        meta=meta, seg_image_path=seg, extra_caveats=caveats,
                        detection=det_eval)
    print()
    print(f"  세그멘테이션 이미지: {seg}")
    print(f"  엑셀 조서:          {xl}")
    return {"result": res, "capture": cap, "seg": seg, "xlsx": xl,
            "name": name, "out_dir": out_dir}


def _truth_depth(cap, lines_xyz):
    """raycast xyz_world 를 조사기 좌표 Z 로 바꿔 복원 깊이와 비교."""
    rt = cap["raw"].get("rig_transform") or {}
    if "laser_pos_world" not in rt:
        return None
    return None      # 자세 부호 규약이 캡처마다 달라 여기서는 생략


def main():
    ap = argparse.ArgumentParser(description="Isaac raycast 내보내기 폴더 검측")
    ap.add_argument("path", help="내보내기 폴더 (또는 --all 과 함께 상위 폴더)")
    ap.add_argument("--all", action="store_true",
                    help="하위 폴더를 모두 처리한다")
    ap.add_argument("--out", default=None, help="산출물 폴더")
    ap.add_argument("--backend", default="geom", choices=["geom", "sam", "vlm"])
    ap.add_argument("--stride", type=int, default=1,
                    help="선 위 점을 N개마다 하나씩 (기본 1 = 전부)")
    ap.add_argument("--site", default=None)
    ap.add_argument("--sigma-u", type=float, default=None,
                    help="선검출 픽셀오차 가정 [px]. 기본은 프로파일 값")
    ap.add_argument("--no-detect-eval", action="store_true",
                    help="선검출 정확도 대조를 건너뛴다 (느릴 때)")
    ap.add_argument("--profile", default=None)
    a = ap.parse_args()
    if a.profile:
        CALIB.use_profile(a.profile)

    targets = ([os.path.join(a.path, d) for d in sorted(os.listdir(a.path))
                if os.path.isdir(os.path.join(a.path, d))
                and os.path.exists(os.path.join(a.path, d,
                                                "camera_params.json"))]
               if a.all else [a.path])
    if not targets:
        print("처리할 폴더가 없다."); return 2
    for t in targets:
        out = (os.path.join(a.out, os.path.basename(os.path.normpath(t)))
               if a.out else None)
        inspect_folder(t, out_dir=out, backend=a.backend,
                       stride=a.stride, site=a.site, sigma_u_px=a.sigma_u,
                       eval_detection=not a.no_detect_eval)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
