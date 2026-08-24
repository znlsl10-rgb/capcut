"""
[식 ③] 수직도·수평도 — 중력(IMU) 기준 통합판
==================================================================
【v2 변경 이유】
  기존 v1은 조사기 좌표계의 특정 축을 직접 읽었다.
    수직도  θ_v = arcsin(|n_y|)
    수평도  θ_h = arccos(|n_z|)
  이는 "장비를 각 검측면에 정면으로 겨눈다"는 전제에서만 성립한다.
  벽 스테이션에서는 중력이 +Y(이미지 아래)로, 바닥 스테이션에서는
  중력이 +Z(광축)로 향하기 때문에 축이 서로 달랐던 것이다.

  세그멘테이션 도입 후에는 한 장의 사진에 벽(정면)과 바닥(경사)이
  동시에 들어오므로 이 전제가 깨진다. 두 면에 대해 동시에 정면일
  수는 없다.

  → 축을 고정하지 않고 **중력벡터 ĝ 를 명시적으로 받는다**.
      벽(면)      θ_vert  = arcsin(|n̂ · ĝ|)      완전수직 → 0°
      바닥(면)    θ_horiz = arccos(|n̂ · ĝ|)      완전수평 → 0°
      동바리(축)  θ_vert  = arccos(|d̂ · ĝ|)      완전수직 → 0°

  기존 식은 이 일반식의 특수해다.
      ĝ = (0,1,0) → arcsin(|n̂·ĝ|) = arcsin(|n_y|)   (v1 수직도와 동일)
      ĝ = (0,0,1) → arccos(|n̂·ĝ|) = arccos(|n_z|)   (v1 수평도와 동일)
  따라서 PDF 5.1 검증값(수직도 오차 0.0008°, 수평도 오차 0°)은
  그대로 재현된다.

【v1 자체검증이 실패하던 이유】
  v1 자체검증의 바닥 법선은 (0, cos2°, sin2°) 즉 Y축을 위로 두는
  좌표계인데 measure_horizontality()는 n_z를 읽어 88°를 출력했다.
  같은 법선에 ĝ=(0,1,0)을 주면 arccos(cos2°) = 2° 로 정상 복원된다.
  축을 코드에 박아둔 것이 원인이었고, 중력을 인자로 받으면 사라진다.

【좌표계 규약 (조사기 좌표계)】
  X : 우측(+)         Y : 하단(+, 이미지 v 증가 방향)
  Z : 전방(+, 작업거리)
  eq1_triangulation 의 Y = (v-cy)·Z/f 규약과 일치.
==================================================================
"""
import numpy as np

# 장비 자세별 기본 중력 방향 (IMU 미제공 시 폴백)
#   벽 검측  : 장비를 세워 수평으로 겨눔 → 중력은 이미지 아래(+Y)
#   바닥 검측: 장비를 아래로 겨눔       → 중력은 광축 방향(+Z)
G_UPRIGHT   = np.array([0.0, 1.0, 0.0])   # 벽·기둥·동바리 검측 자세
G_LOOKDOWN  = np.array([0.0, 0.0, 1.0])   # 바닥·슬래브 검측 자세

# KCS 허용 기준 (PDF 1.2 표). length_m 이 주어지면 mm 판정, 없으면 각도 판정.
KCS_SPEC = {
    "wall":     {"tol_mm": 20.0, "tol_ratio": 1/1000, "tol_deg": 0.5},
    "column":   {"tol_mm": 20.0, "tol_ratio": 1/1000, "tol_deg": 0.5},
    "shoring":  {"tol_mm": 20.0, "tol_ratio": 1/1000, "tol_deg": 0.5},
    "rebar":    {"tol_mm": 20.0, "tol_ratio": 1/1000, "tol_deg": 0.5},
    "formwork": {"tol_mm": 20.0, "tol_ratio": None,   "tol_deg": 0.5},
    "masonry":  {"tol_mm": 10.0, "tol_ratio": None,   "tol_deg": 0.5},
    "floor":    {"tol_mm": 20.0, "tol_ratio": None,   "tol_deg": 0.5},
    "slab":     {"tol_mm": 20.0, "tol_ratio": None,   "tol_deg": 0.5},
}


# =====================================================================
# 중력벡터 준비
# =====================================================================
def normalize(v):
    v = np.asarray(v, dtype=float).reshape(3)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError("영벡터는 방향을 가질 수 없습니다.")
    return v / n


def gravity_in_laser_frame(g_imu, R_ic=None, R_cl=None):
    """
    IMU 가속도계가 읽은 중력벡터를 조사기 좌표계로 변환한다.

    PDF 3.1 캘리브레이션 B 표의 `R_ic`(IMU–카메라 상대자세)를 사용한다.

    Parameters
    ----------
    g_imu : (3,)
        IMU 좌표계에서 측정한 중력 방향. 정지 상태 가속도계 출력의
        부호를 뒤집은 값(= 실제 중력이 향하는 방향). 크기는 무관.
    R_ic : (3,3) or None
        IMU → 카메라 회전. None이면 단위행렬(IMU가 카메라와 정렬).
    R_cl : (3,3) or None
        카메라 → 조사기 회전. None이면 단위행렬.
        현재 하드웨어는 두 광학계가 평행하고 오프셋만 있으므로 I.

    Returns
    -------
    g_hat : (3,) 단위벡터 — 조사기 좌표계에서 중력이 향하는 방향
    """
    g = normalize(g_imu)
    if R_ic is not None:
        g = np.asarray(R_ic, dtype=float) @ g
    if R_cl is not None:
        g = np.asarray(R_cl, dtype=float) @ g
    return normalize(g)


def _resolve_gravity(g_hat, fallback):
    if g_hat is None:
        return normalize(fallback)
    return normalize(g_hat)


# =====================================================================
# 통합 측정식
# =====================================================================
def measure_from_gravity(vec, g_hat, kind):
    """
    중력 기준 자세 이탈각 통합 계산.

    Parameters
    ----------
    vec : (3,)
        kind 가 plane_* 이면 평면 법선 n, axis_* 이면 부재 축 방향 d.
    g_hat : (3,)
        조사기 좌표계 중력 단위벡터.
    kind : {"plane_vertical", "plane_horizontal", "axis_vertical"}
        plane_vertical   : 벽·거푸집·조적 — 법선이 중력과 수직이어야 함
        plane_horizontal : 바닥·슬래브   — 법선이 중력과 평행해야 함
        axis_vertical    : 동바리·기둥·철근 — 축이 중력과 평행해야 함

    Returns
    -------
    theta_deg : float — 기준에서 벗어난 각도 [°], 0에 가까울수록 양호
    """
    v = normalize(vec)
    g = normalize(g_hat)
    c = float(np.clip(abs(np.dot(v, g)), 0.0, 1.0))

    if kind == "plane_vertical":
        # 완전 수직벽: 법선 ⊥ 중력 → |n·g| = 0 → 0°
        return float(np.degrees(np.arcsin(c)))
    if kind in ("plane_horizontal", "axis_vertical"):
        # 완전 수평바닥 / 완전 수직부재: |v·g| = 1 → 0°
        return float(np.degrees(np.arccos(c)))
    raise ValueError(f"알 수 없는 kind: {kind}")


def measure_verticality(plane_normal, g_hat=None):
    """
    수직도 — 벽면이 연직에서 벗어난 각도.

    g_hat 미지정 시 G_UPRIGHT=(0,1,0)을 사용하며, 이는 v1의
    arcsin(|n_y|)와 수치적으로 동일하다(하위호환).
    """
    return measure_from_gravity(plane_normal,
                                _resolve_gravity(g_hat, G_UPRIGHT),
                                "plane_vertical")


def measure_horizontality(plane_normal, g_hat=None):
    """
    수평도 — 바닥이 수평에서 벗어난 각도.

    g_hat 미지정 시 G_LOOKDOWN=(0,0,1)을 사용하며, 이는 v1의
    arccos(|n_z|)와 수치적으로 동일하다(하위호환).
    실제 검측에서는 IMU로 얻은 g_hat 을 반드시 넘길 것.
    """
    return measure_from_gravity(plane_normal,
                                _resolve_gravity(g_hat, G_LOOKDOWN),
                                "plane_horizontal")


def measure_axis_verticality(axis_dir, g_hat=None):
    """
    선형 부재(동바리·기둥·철근) 수직도 — 부재 축이 연직에서 벗어난 각도.

    평면이 아니므로 법선이 아니라 축 방향 d̂ 를 받는다.
    d̂ 는 eq2_plane_fit.fit_axis_pca() 로 구한다.
    """
    return measure_from_gravity(axis_dir,
                                _resolve_gravity(g_hat, G_UPRIGHT),
                                "axis_vertical")


# =====================================================================
# 판정
# =====================================================================
def deviation_mm(theta_deg, member_length_m):
    """
    각도 이탈을 부재 전길이 기준 mm 편차로 환산.

    KCS는 수직 부재를 각도가 아니라 mm(±20mm, h/1000)로 규정한다.
    세그멘테이션이 부재 영역의 3D 범위를 주므로 member_length_m 을
    실측할 수 있고, 그때 비로소 mm 판정이 가능해진다.
    """
    return float(abs(member_length_m) * np.tan(np.radians(abs(theta_deg))) * 1000.0)


def judge_pass_fail(theta_deg, tolerance_deg=0.5):
    """각도 기준 단순 판정 (v1 호환)."""
    return bool(abs(theta_deg) <= tolerance_deg)


def judge_kcs(theta_deg, member_class, member_length_m=None):
    """
    KCS 기준 판정.

    member_length_m 이 있으면 시방 본기준(tol_mm)으로 mm 판정하고,
    "층고대비 권장"인 h/1000(tol_ratio)은 본판정을 덮어쓰지 않고
    allow_mm_recommended / is_pass_recommended 로 병기한다.
    member_length_m 이 없으면 각도 기준(tol_deg)으로 판정한다.

    Returns
    -------
    dict — {is_pass, basis, theta_deg, deviation_mm, allow_mm, allow_deg}
    """
    spec = KCS_SPEC.get(member_class, {"tol_mm": 20.0, "tol_ratio": None,
                                       "tol_deg": 0.5})
    out = {"member_class": member_class,
           "theta_deg": round(float(theta_deg), 4),
           "allow_deg": spec["tol_deg"]}

    if member_length_m is None or member_length_m <= 0:
        out.update(basis="angle", deviation_mm=None, allow_mm=None,
                   is_pass=bool(abs(theta_deg) <= spec["tol_deg"]))
        return out

    dev = deviation_mm(theta_deg, member_length_m)
    allow = float(spec["tol_mm"])          # 시방 본기준 (±20mm 등)
    out.update(basis="mm", deviation_mm=round(dev, 3),
               allow_mm=round(allow, 3),
               member_length_m=round(float(member_length_m), 4),
               is_pass=bool(dev <= allow))

    # h/1000 은 PDF 1.2 표에서 "층고대비 권장"으로 병기된 값이므로
    # 본판정을 덮어쓰지 않고 별도 권장기준으로만 함께 보고한다.
    if spec["tol_ratio"] is not None:
        allow_rec = member_length_m * 1000.0 * spec["tol_ratio"]
        out["allow_mm_recommended"] = round(float(allow_rec), 3)
        out["is_pass_recommended"]  = bool(dev <= allow_rec)
    return out


# ============ 자체 검증 ============
if __name__ == "__main__":
    def _rx(deg):
        r = np.radians(deg)
        return np.array([[1, 0, 0],
                         [0, np.cos(r), -np.sin(r)],
                         [0, np.sin(r),  np.cos(r)]])

    ok = True
    print("[식 ③ v2] 중력 기준 수직도·수평도·부재 수직도 검증")

    # ── 1. 하위호환: v1 수직도 규약 (ĝ=(0,1,0) 기본값) ──
    n_wall = _rx(3.0) @ np.array([0, 0, -1.0])
    tv = measure_verticality(n_wall)
    ok &= abs(tv - 3.0) < 1e-6
    print(f"  [1] 수직도(기본 ĝ)      측정 {tv:8.4f}° / 참값 3.0000° "
          f"오차 {abs(tv-3):.2e}° {'PASS' if abs(tv-3)<1e-6 else 'FAIL'}")

    # ── 2. v1이 실패하던 케이스: Y-up 좌표계 바닥 법선 ──
    #      v1은 n_z를 읽어 88° 출력. ĝ를 명시하면 2°로 복원된다.
    n_floor_yup = _rx(2.0) @ np.array([0, 1.0, 0])
    th_v1 = measure_horizontality(n_floor_yup)                 # 기본 ĝ=(0,0,1)
    th_v2 = measure_horizontality(n_floor_yup, g_hat=G_UPRIGHT)  # 올바른 ĝ
    ok &= abs(th_v2 - 2.0) < 1e-6
    print(f"  [2] 수평도(축 고정, v1)  측정 {th_v1:8.4f}° / 참값 2.0000° "
          f"← v1이 실패하던 지점")
    print(f"      수평도(ĝ 명시, v2)  측정 {th_v2:8.4f}° / 참값 2.0000° "
          f"오차 {abs(th_v2-2):.2e}° {'PASS' if abs(th_v2-2)<1e-6 else 'FAIL'}")

    # ── 3. 하위호환: 바닥 스테이션 규약 (장비 하방, ĝ=(0,0,1)) ──
    n_floor_zdn = _rx(2.0) @ np.array([0, 0, -1.0])
    th = measure_horizontality(n_floor_zdn)
    ok &= abs(th - 2.0) < 1e-6
    print(f"  [3] 수평도(바닥 스테이션) 측정 {th:8.4f}° / 참값 2.0000° "
          f"오차 {abs(th-2):.2e}° {'PASS' if abs(th-2)<1e-6 else 'FAIL'}")

    # ── 4. 임의 자세: 장비를 30° 기울여 들어도 결과 불변 ──
    #      점군과 중력을 함께 회전시키면 측정값이 같아야 한다.
    Rt = _rx(30.0)
    tv_rot = measure_verticality(Rt @ n_wall, g_hat=Rt @ G_UPRIGHT)
    ok &= abs(tv_rot - 3.0) < 1e-6
    print(f"  [4] 장비 30° 기울임      측정 {tv_rot:8.4f}° / 참값 3.0000° "
          f"오차 {abs(tv_rot-3):.2e}° {'PASS' if abs(tv_rot-3)<1e-6 else 'FAIL'}")

    # ── 5. 선형 부재(동바리) 축 수직도 + mm 환산 ──
    d_shoring = _rx(1.2) @ np.array([0, -1.0, 0])   # 연직에서 1.2° 기움
    ta = measure_axis_verticality(d_shoring)
    ok &= abs(ta - 1.2) < 1e-6
    jd = judge_kcs(ta, "shoring", member_length_m=2.7)
    print(f"  [5] 동바리 축 수직도     측정 {ta:8.4f}° / 참값 1.2000° "
          f"오차 {abs(ta-1.2):.2e}° {'PASS' if abs(ta-1.2)<1e-6 else 'FAIL'}")
    print(f"      → 길이 2.7m 환산 편차 {jd['deviation_mm']:.2f}mm "
          f"(본기준 {jd['allow_mm']:.1f}mm → "
          f"{'합격' if jd['is_pass'] else '기준초과'} / "
          f"권장 h/1000 {jd['allow_mm_recommended']:.2f}mm → "
          f"{'합격' if jd['is_pass_recommended'] else '기준초과'})")

    # ── 6. IMU → 조사기 좌표계 변환 ──
    g = gravity_in_laser_frame([0.0, 9.79, 0.12])
    ok &= abs(np.linalg.norm(g) - 1.0) < 1e-12
    print(f"  [6] IMU 중력 변환        ĝ = ({g[0]:.4f}, {g[1]:.4f}, {g[2]:.4f}) "
          f"|ĝ|={np.linalg.norm(g):.6f} PASS")

    print(f"\n  전체: {'✓ ALL PASS' if ok else '✗ FAIL 있음'}")
