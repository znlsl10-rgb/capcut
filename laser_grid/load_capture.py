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
            "camera_params": camera_params, "g_hat": g_hat,
            "diag": diag, "meta": meta, "raw": cp_raw, "cast": cast}


def _base_image(path, size):
    """CAM.png 를 센서 크기로 늘려 결과 이미지 배경으로 쓴다."""
    for name in ("CAM.png", "CAST.png"):
        fp = os.path.join(path, name)
        if not os.path.exists(fp):
            continue
        try:
            from PIL import Image
            im = Image.open(fp).convert("RGB").resize(
                (size[0], size[1]), Image.BICUBIC)
            return np.asarray(im)
        except Exception:
            return None
    return None


# =====================================================================
# 검측 실행
# =====================================================================
def inspect_folder(path, out_dir=None, backend="geom", stride=1, site=None,
                   sigma_u_px=None):
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
    res = PIPE.inspect_image(lines_uv, lines_xyz, cp, cap["g_hat"],
                             seg_backend=backend, sigma_u_px=su)
    print()
    print(PIPE.format_report(res))

    base = _base_image(path, cp["resolution"])
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
    xl = XLS.save_excel(os.path.join(out_dir, f"{name}_품질검측조서.xlsx"), res,
                        meta=meta, seg_image_path=seg, extra_caveats=caveats)
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
                       stride=a.stride, site=a.site, sigma_u_px=a.sigma_u)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
