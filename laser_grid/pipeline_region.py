#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_region.py — 이미지 1장 → 영역별 품질검측
========================================================================
현장 사진 한 장에 벽·바닥·동바리·철근이 함께 들어와도, 영역을 나눠
각 부재에 맞는 검측식을 적용한다.

  1 shot = (rgb_off, rgb_on, IMU ĝ, calib)
   ├─[A ] 선검출        rgb_on  → {lid: [(u,v)…]}
   ├─[C ] 영역분할      rgb_off → label_map / point_labels
   ├─[eq1] 삼각측량             → (X,Y,Z) 조사기 좌표계
   ├─[eq5] 영역 할당            → 침식·깊이불연속 제거 + 의미x기하 융합
   └─ 영역별 검측
       벽·거푸집·조적  → eq2 평면(TLS) → eq3 수직도(중력) + eq4 평활도(면내)
       바닥·슬래브     → eq2 평면(TLS) → eq3 수평도(중력) + eq4 평활도(면내)
       동바리·기둥·철근 → eq2 축(PCA)  → eq3 축 수직도(중력)  [평활도 N/A]
       전 영역        → eq5 불확실도 → KCS 합격/기준초과/측정불가

기존 inspection.py 는 STATIONS 딕셔너리에 "이 스테이션은 수직도" 라고
적어두고 화면 전체를 단일 평면으로 적합했다. 이 모듈은 그 결정을 설정이
아니라 인지 결과에서 가져온다.

실행 (합성 씬 자체검증):
  python3 pipeline_region.py
========================================================================
"""
import numpy as np
import importlib.util as _ilu, os as _os


def _load(name):
    spec = _ilu.spec_from_file_location(
        name, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), f"{name}.py"))
    m = _ilu.module_from_spec(spec); spec.loader.exec_module(m)
    return m


_EQ1 = _load("eq1_triangulation")
_EQ2 = _load("eq2_plane_fit")
_EQ3 = _load("eq3_orientation")
_EQ4 = _load("eq4_flatness_line")
_EQ5 = _load("eq5_region_assign")
_EQ6 = _load("eq6_straightedge")
_SEG = _load("C_영역분할")

# 평활도 허용 기준 (PDF 1.2 표: 노출 콘크리트 3m당 7mm, 미장 1m당 10mm 등).
# 면적 기준이 아니라 구간 기준이므로 영역 크기와 함께 판정한다.
FLATNESS_TOL_MM = {"wall": 7.0, "plaster_wall": 10.0, "masonry": 10.0,
                   "formwork_wall": 7.0, "formwork_column": 7.0,
                   "floor": 10.0, "slab": 10.0, "ceiling": 3.0}


# =====================================================================
# 영역 1개 검측
# =====================================================================
def measure_region(points_3d, cls, g_hat, camera_params,
                   flatness_threshold_mm=1.5, sigma_u_px=0.2,
                   target_sigma_mm=2.0):
    """
    한 영역의 3D 점군에 클래스에 맞는 검측식을 적용한다.

    Returns
    -------
    dict — kind, theta_deg, judge, flatness, uncertainty, n_points, status
        status : "measured" | "rejected"
    """
    pts = np.asarray(points_3d, dtype=float)
    kind = _EQ5.MEASURE_KIND.get(cls)
    kcs_cls = _EQ5.KCS_CLASS.get(cls, cls)
    out = {"class": cls, "kind": kind, "n_points": int(len(pts)),
           "status": "rejected", "reject_reason": None,
           "theta_deg": None, "judge": None,
           "flatness": None, "uncertainty": None}

    if kind is None:
        out["reject_reason"] = f"검측 대상 클래스 아님 ({cls})"
        return out
    if len(pts) < 12:
        out["reject_reason"] = f"점 부족 ({len(pts)} < 12)"
        return out

    # ── 선형 부재: 축 적합 ──
    if kind == "axis_vertical":
        ax = _EQ2.fit_axis_pca(pts)
        out["axis"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                       for k, v in ax.items() if k != "reject_reason"}
        if not ax["is_valid"]:
            out["reject_reason"] = ax["reject_reason"]
            return out
        theta = _EQ3.measure_axis_verticality(ax["direction"], g_hat)
        out["theta_deg"] = round(theta, 4)
        out["judge"] = _EQ3.judge_kcs(theta, kcs_cls,
                                      member_length_m=ax["length_m"])
        out["uncertainty"] = _EQ5.region_uncertainty(
            pts, camera_params, normal=None, sigma_u_px=sigma_u_px,
            target_sigma_mm=target_sigma_mm)
        # 평활도는 원통면이라 성립하지 않음
        out["flatness"] = {"applicable": False,
                           "reason": "선형 부재(원통면) — 평활도 정의 없음"}
        out["status"] = "measured"
        return out

    # ── 면 부재: 방향 무관 TLS 평면 적합 ──
    plane, inliers = _EQ2.fit_plane_tls_ransac(pts, threshold=0.01)
    normal = np.array(plane[:3], dtype=float)
    out["plane"] = [round(float(x), 6) for x in plane]
    out["plane_inliers"] = int(inliers.sum())

    theta = _EQ3.measure_from_gravity(normal, g_hat, kind)
    out["theta_deg"] = round(theta, 4)
    out["judge"] = _EQ3.judge_kcs(theta, kcs_cls, member_length_m=None)

    unc = _EQ5.region_uncertainty(pts, camera_params, normal=normal,
                                  sigma_u_px=sigma_u_px,
                                  target_sigma_mm=target_sigma_mm)
    out["uncertainty"] = unc

    # ── 평활도 ──
    # 두 가지를 함께 낸다. 쓰임이 다르다.
    #   eq4 : 요철의 위치·개수·깊이를 찾는다 (어디가 문제인지)
    #   eq6 : KCS 가 규정한 직선자 처짐량으로 판정한다 (합격인지)
    # 전역 평면 잔차(eq4)로는 시방 판정을 할 수 없다. 넓은 면이 완만히
    # 휘면 잔차는 크지만 3m 자에는 안 걸리고, 좁고 급한 굴곡은 그 반대다.
    fd = _EQ4.detect_defects_region(pts, plane=plane,
                                    threshold_mm=flatness_threshold_mm)
    flat = {"applicable": True,
            "defect_max_dev_mm": round(fd["overall_max_dev_mm"], 3),
            "rms_dev_mm": round(fd["rms_dev_mm"], 3),
            "raw_max_dev_mm": round(fd["raw_max_dev_mm"], 3),
            "defect_clusters": len(fd["verified_clusters"]),
            "defect_count": fd["defect_count"],
            "reject_reason": fd.get("reject_reason")}

    kcs = _EQ6.judge_kcs_flatness(
        pts, cls, plane=plane,
        sigma_normal_mm=(None if unc["flatness_measurable"]
                         else unc["sigma_normal_mm"]),
        target_sigma_mm=target_sigma_mm)
    flat["kcs"] = kcs
    flat["judgement"] = kcs["judgement"]
    flat["is_pass"] = kcs["is_pass"]
    if kcs["checks"]:
        c0 = max(kcs["checks"], key=lambda x: x.get("ratio") or 0.0)
        flat["straightedge_length_m"] = c0["length_m"]
        flat["max_gap_mm"] = c0["max_gap_mm"]
        flat["upper_estimate_mm"] = c0["upper_estimate_mm"]
        flat["tolerance_mm"] = c0["tolerance_mm"]
    if not unc["flatness_measurable"]:
        flat["note"] = (f"법선방향 불확실도 σ_n={unc['sigma_normal_mm']}mm > "
                        f"목표 {target_sigma_mm}mm "
                        f"(Z={unc['z_mean_m']}m, 입사각 {unc['incidence_deg']}°)")
    elif kcs.get("note"):
        flat["note"] = kcs["note"]
    out["flatness"] = flat
    out["status"] = "measured"
    return out


# =====================================================================
# 한 장 전체 검측
# =====================================================================
def inspect_image(lines_pixels, lines_xyz, camera_params, g_hat,
                  rgb_off=None, seg_backend="gt", seg_kwargs=None,
                  erode_default_px=3, erode_thin_px=1,
                  min_region_points=12, sigma_u_px=0.2,
                  target_sigma_mm=2.0, flatness_threshold_mm=1.5):
    """
    선검출 결과 + 삼각측량 결과 + 세그멘테이션으로 영역별 검측을 수행한다.

    Parameters
    ----------
    lines_pixels : {lid: [(u,v), ...]}   A_선검출 출력 (ON 프레임)
    lines_xyz    : {lid: [(X,Y,Z), ...]} eq1 삼각측량 결과 (같은 순서)
    camera_params: dict — f_px, b_m, cx_px, cy_px
    g_hat        : (3,) 조사기 좌표계 중력 단위벡터 (eq3.gravity_in_laser_frame)
    rgb_off      : (H,W,3) 레이저 OFF 프레임 — 세그멘테이션 입력
    seg_backend  : "gt" | "geom" | "sam" | "vlm"
    seg_kwargs   : 백엔드 인자 (gt → label_map, id_to_semantic)

    Returns
    -------
    dict — regions, summary, segmentation, assign_stats
    """
    seg_kwargs = dict(seg_kwargs or {})
    table = _EQ5.build_point_table(lines_pixels, lines_xyz)
    if len(table["xyz"]) == 0:
        return {"regions": [], "summary": {"n_regions": 0},
                "error": "삼각측량된 격자점이 없습니다."}

    # ── [C] 영역 분할 ──
    if seg_backend == "geom":
        seg_kwargs.setdefault("table", table)
        seg_kwargs.setdefault("g_hat", g_hat)
        seg_kwargs.setdefault("camera_params", camera_params)
    seg = _SEG.segment(rgb_off, backend=seg_backend, **seg_kwargs)

    # ── [eq5] 점 → 영역 ──
    if seg["label_map"] is not None:
        regions, stats = _EQ5.assign_points_to_regions(
            table, seg["label_map"], seg["class_names"],
            erode_default_px=erode_default_px, erode_thin_px=erode_thin_px,
            min_points=min_region_points)
    else:
        regions, stats = _regions_from_point_labels(
            table, seg["point_labels"], seg["class_names"],
            min_points=min_region_points)

    # ── 영역별 검측 ──
    results = []
    for reg in regions:
        pts = table["xyz"][reg["idx"]]
        ev = _EQ5.geometric_evidence(pts, g_hat)
        fu = _EQ5.fuse_label(reg["class"], ev)
        final_cls = fu["final_class"]

        r = measure_region(pts, final_cls, g_hat, camera_params,
                           flatness_threshold_mm=flatness_threshold_mm,
                           sigma_u_px=sigma_u_px,
                           target_sigma_mm=target_sigma_mm)
        r["region_id"] = int(reg["class_id"])
        r["label_fusion"] = {k: v for k, v in fu.items() if k != "note"}
        r["label_fusion_note"] = fu["note"]
        r["geom_shape"] = ev["shape"]
        results.append(r)

    measured = [r for r in results if r["status"] == "measured"]
    summary = {
        "n_regions": len(results),
        "n_measured": len(measured),
        "n_rejected": len(results) - len(measured),
        "classes": sorted({r["class"] for r in results}),
        "label_corrections": sum(1 for r in results
                                 if r["label_fusion"]["source"] == "geometric"),
        "flatness_unmeasurable": sum(
            1 for r in measured
            if (r["flatness"] or {}).get("judgement") == "측정불가"),
    }
    return {"regions": results, "summary": summary,
            "segmentation": {"backend": seg["backend"], "meta": seg["meta"]},
            "assign_stats": stats}


def _regions_from_point_labels(table, point_labels, class_names, min_points=12):
    """geom 백엔드처럼 점 단위 라벨을 주는 경우의 영역 구성."""
    labels = np.asarray(point_labels)
    disc = _EQ5.mark_depth_discontinuity(table)
    stats = {"total": len(labels), "out_of_image": 0, "ignored_class": 0,
             "eroded_away": 0, "discontinuity": int(disc.sum()), "assigned": 0}
    regions = []
    for cid in np.unique(labels):
        cls = class_names.get(int(cid), "background")
        keep = (labels == cid) & ~disc
        if cls in _EQ5.IGNORE_CLASSES:
            stats["ignored_class"] += int((labels == cid).sum())
            continue
        if keep.sum() < min_points:
            continue
        idx = np.where(keep)[0]
        stats["assigned"] += len(idx)
        regions.append({"class": cls, "class_id": int(cid), "idx": idx,
                        "n_points": int(len(idx))})
    return regions, stats


# =====================================================================
# 촬영 결과 → 검측 (Isaac 비의존)
# =====================================================================
def triangulate_lines(lines_pixels, line_angles, camera_params):
    """
    검출된 선의 픽셀점을 eq1 로 3D 로 되돌린다.

    V선만 처리하는 이유
    ------------------
    기선이 X축 방향이라 시차는 u 좌표에만 나타나고, 깊이를 풀려면 그 점의
    발사각 α 를 알아야 한다.
      · V선 : α 가 선마다 고정 → 선을 따라 조밀 샘플링해도 전부 풀린다
      · H선 : β 만 고정이고 α 는 점마다 다르다. v 좌표는 (v-c_y)/f = tanβ
              라는 이미 아는 사실만 되풀이하므로 깊이 정보가 없다.
    따라서 H선은 V선과의 교점에서만 α 를 회복할 수 있고, 그 교점은 이미
    V선 샘플에 포함된다. V선 조밀 샘플링이 곧 완전한 정보다.

    Returns
    -------
    lines_xyz : {lid: [(X,Y,Z), ...]}
    lines_uv  : {lid: [(u,v), ...]}   삼각측량에 성공한 점만 (순서 일치)
    """
    f = float(camera_params["f_px"]); b = float(camera_params["b_m"])
    cx = float(camera_params["cx_px"]); cy = float(camera_params["cy_px"])
    lines_xyz, lines_uv, skipped = {}, {}, []

    for lid, pts in lines_pixels.items():
        info = line_angles.get(lid)
        if info is None:
            continue
        if info.get("fixed") != "alpha":
            skipped.append(lid)
            continue
        alpha = float(info["angle_rad"])
        xyz, uv = [], []
        for p in pts:
            u, v = float(p[0]), float(p[1])
            try:
                X, Y, Z = _EQ1.triangulate_point(u, v, alpha, 0.0, f, b, cx, cy)
            except ValueError:
                continue                      # 시차 음수 = 캘리브레이션 이상
            if not np.isfinite(Z) or Z <= 0:
                continue
            xyz.append([X, Y, Z]); uv.append([u, v])
        if len(xyz) >= 5:
            lines_xyz[lid] = xyz
            lines_uv[lid] = uv
    return lines_xyz, lines_uv, skipped


def inspect_capture(lines_pixels, line_angles, camera_params, R_world_cam,
                    label_map=None, id_to_semantic=None, rgb_off=None,
                    g_hat=None, backend=None, **kw):
    """
    한 번의 촬영 결과를 받아 영역별 검측까지 수행한다.

    inspection.py(Isaac)와 오프라인 검증 양쪽에서 같은 코드를 쓰기 위해
    Isaac 의존성을 두지 않는다.

    Parameters
    ----------
    R_world_cam : (3,3) or None
        카메라 자세행렬. 주면 여기서 중력을 유도한다(g_hat 미지정 시).
    label_map, id_to_semantic : Isaac 시맨틱 어노테이터 출력
        있으면 backend='gt', 없으면 backend='geom' 으로 자동 폴백.
    """
    if g_hat is None:
        if R_world_cam is None:
            raise ValueError("g_hat 또는 R_world_cam 중 하나는 필요합니다 "
                             "(중력 기준 없이는 수직·수평도를 정의할 수 없음).")
        g_hat = _EQ3.gravity_from_camera_rotation(R_world_cam)

    lines_xyz, lines_uv, skipped = triangulate_lines(
        lines_pixels, line_angles, camera_params)
    if not lines_xyz:
        return {"regions": [], "summary": {"n_regions": 0},
                "error": "삼각측량 가능한 V선이 없습니다.",
                "skipped_lines": skipped}

    if backend is None:
        backend = "gt" if label_map is not None else "geom"
    seg_kwargs = ({"label_map": label_map, "id_to_semantic": id_to_semantic}
                  if backend == "gt" else {})

    res = inspect_image(lines_uv, lines_xyz, camera_params, g_hat,
                        rgb_off=rgb_off, seg_backend=backend,
                        seg_kwargs=seg_kwargs, **kw)
    res["gravity_laser_frame"] = [round(float(x), 6) for x in np.asarray(g_hat)]
    res["skipped_lines"] = skipped
    res["n_triangulated"] = int(sum(len(v) for v in lines_xyz.values()))
    return res


# =====================================================================
# 보고
# =====================================================================
def format_report(result):
    """영역별 검측 결과를 사람이 읽는 표로 만든다."""
    lines = []
    s = result["summary"]
    seg = result.get("segmentation", {})
    lines.append(f"세그멘테이션 backend={seg.get('backend')}  "
                 f"영역 {s['n_regions']}개 (검측 {s['n_measured']} / "
                 f"기각 {s['n_rejected']})  라벨교정 {s['label_corrections']}건")
    st = result.get("assign_stats", {})
    if st:
        lines.append(f"  점 배분: 전체 {st['total']} → 할당 {st['assigned']} "
                     f"(화면밖 {st['out_of_image']}, 비검측 {st['ignored_class']}, "
                     f"침식 {st['eroded_away']}, 깊이불연속 {st['discontinuity']})")
    lines.append("")
    hdr = (f"  {'클래스':<14}{'검측':<10}{'각도(°)':>9}{'판정':>10}"
           f"{'자처짐(mm)':>12}{'평활판정':>10}{'σ_n(mm)':>9}{'점수':>7}")
    lines.append(hdr)
    lines.append("  " + "-" * (len(hdr) - 2))
    kind_ko = {"plane_vertical": "수직도", "plane_horizontal": "수평도",
               "axis_vertical": "축수직도"}
    for r in result["regions"]:
        if r["status"] != "measured":
            lines.append(f"  {r['class']:<14}{'기각':<10}"
                         f"{'-':>9}{'-':>10}{'-':>12}{'-':>10}{'-':>9}"
                         f"{r['n_points']:>7}   ← {r['reject_reason']}")
            continue
        j = r["judge"] or {}
        verdict = "합격" if j.get("is_pass") else "기준초과"
        f = r["flatness"] or {}
        fmax = (f"{f.get('max_gap_mm', 0.0):.2f}" if f.get("applicable")
                else "N/A")
        fjud = f.get("judgement", "N/A") if f.get("applicable") else "N/A"
        sn = r["uncertainty"]["sigma_normal_mm"]
        lines.append(f"  {r['class']:<14}{kind_ko.get(r['kind'], r['kind']):<10}"
                     f"{r['theta_deg']:>9.4f}{verdict:>10}"
                     f"{fmax:>12}{fjud:>10}{sn:>9.2f}{r['n_points']:>7}")
        if r["label_fusion"]["source"] == "geometric":
            lines.append(f"      ↳ 라벨 교정: {r['label_fusion_note']}")
        if f.get("judgement") == "측정불가":
            lines.append(f"      ↳ {f['note']}")
    return "\n".join(lines)


# ============ 자체 검증 ============
if __name__ == "__main__":
    _SYN = _load("synth_scene")
    print("=" * 78)
    print("영역별 품질검측 파이프라인 — 합성 씬 자체검증")
    print("=" * 78)
    scene = _SYN.build_scene()
    print(_SYN.describe(scene))
    print()

    for backend in ("gt", "geom"):
        kw = ({"label_map": scene["label_map"],
               "id_to_semantic": scene["id_to_semantic"]}
              if backend == "gt" else {})
        res = inspect_image(scene["lines_pixels"], scene["lines_xyz"],
                            scene["camera_params"], scene["g_hat"],
                            rgb_off=scene["rgb_off"],
                            seg_backend=backend, seg_kwargs=kw)
        print(f"── backend = {backend} " + "─" * 55)
        print(format_report(res))
        print()
        print(_SYN.score(scene, res))
        print()
