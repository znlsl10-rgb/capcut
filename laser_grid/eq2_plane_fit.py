"""
[식 ②·③] 평면 fitting + 잔차
================================
평면 방정식: aX + bY + cZ + d = 0
RANSAC으로 inlier 평면 추출 → 법선 n = (a, b, c)

잔차: e(i,j) = (a·X + b·Y + c·Z + d) / √(a² + b² + c²)
"""
import numpy as np

try:
    from sklearn.linear_model import RANSACRegressor, LinearRegression
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


def fit_plane_lstsq(points_3d):
    """
    최소제곱 평면 fitting (RANSAC 없음).
    
    Returns: (a, b, c, d) — 정규화된 법선 + offset
    """
    A = np.column_stack([points_3d[:, 0], points_3d[:, 1], np.ones(len(points_3d))])
    coeffs, _, _, _ = np.linalg.lstsq(A, points_3d[:, 2], rcond=None)
    a_p, b_p, c_p = coeffs
    
    # 표준형: a'X + b'Y - Z + c' = 0
    a, b, c, d = a_p, b_p, -1.0, c_p
    norm = np.sqrt(a**2 + b**2 + c**2)
    
    return a/norm, b/norm, c/norm, d/norm


def fit_plane_ransac(points_3d, threshold=0.005, min_samples=3):
    """
    RANSAC 평면 fitting (outlier robust).
    
    Parameters
    ----------
    threshold : float - inlier 판정 잔차 (m). 기본 5mm.
    
    Returns
    -------
    plane : tuple (a, b, c, d) — 정규화된
    inlier_mask : ndarray (N,) - True/False
    """
    if not HAS_SKLEARN:
        # sklearn 없으면 최소제곱으로 대체
        plane = fit_plane_lstsq(points_3d)
        inlier_mask = np.ones(len(points_3d), dtype=bool)
        return plane, inlier_mask
    
    X_feat = points_3d[:, :2]
    Z_target = points_3d[:, 2]
    
    ransac = RANSACRegressor(
        estimator=LinearRegression(),
        residual_threshold=threshold,
        min_samples=min_samples,
        random_state=42,
    )
    ransac.fit(X_feat, Z_target)
    
    a_p, b_p = ransac.estimator_.coef_
    c_p = ransac.estimator_.intercept_
    
    a, b, c, d = a_p, b_p, -1.0, c_p
    norm = np.sqrt(a**2 + b**2 + c**2)
    
    return (a/norm, b/norm, c/norm, d/norm), ransac.inlier_mask_


def compute_residuals(points_3d, plane):
    """
    부호 있는 잔차 e_(i,j) = (aX+bY+cZ+d) / √(a²+b²+c²)
    
    (이미 정규화된 plane 입력 가정 → 분모 = 1)
    
    Returns: residuals (N,) - 단위 m
    """
    a, b, c, d = plane
    return a * points_3d[:, 0] + b * points_3d[:, 1] + c * points_3d[:, 2] + d


# ============ 자체 검증 ============
if __name__ == "__main__":
    np.random.seed(42)
    
    # 25점 격자, 중앙(2,2)에 5mm 돌출
    pts = []
    for i in range(5):
        for j in range(5):
            x = -0.1 + i * 0.05
            y = -0.1 + j * 0.05
            z = 1.0
            if i == 2 and j == 2:
                z -= 0.005  # 5mm 돌출 (카메라 방향)
            z += np.random.normal(0, 0.0005)  # 노이즈 0.5mm
            pts.append([x, y, z])
    pts = np.array(pts)
    
    plane, inliers = fit_plane_ransac(pts)
    res = compute_residuals(pts, plane)
    e_max = np.max(np.abs(res)) * 1000
    e_rms = np.sqrt(np.mean(res**2)) * 1000
    
    print(f"[식 ②] 평면 fitting 검증")
    print(f"  법선 n = ({plane[0]:.4f}, {plane[1]:.4f}, {plane[2]:.4f})")
    print(f"  e_max: {e_max:.3f} mm (참값 5mm 돌출)")
    print(f"  e_RMS: {e_rms:.3f} mm")
    print(f"  Inlier: {inliers.sum()}/{len(pts)} 점")
    print(f"  결과: {'✓ PASS' if abs(e_max - 5) < 1 else '✗ FAIL'}")


# =====================================================================
# [v2 추가] 방향 무관 평면 적합 — 전최소제곱(TLS) RANSAC
# =====================================================================
# fit_plane_ransac() 은 Z = aX + bY + c 로 회귀하므로, 광축과 나란한 면
# (한 장에 같이 찍힌 바닥처럼 비스듬히 들어온 면)은 Z가 (X,Y)의 함수가
# 아니어서 표현 자체가 불가능하다. 스테이션마다 면을 정면으로 겨누던
# 기존 파이프라인에서는 드러나지 않던 한계이나, 영역별 검측에서는
# 반드시 터진다.
#
# → 종속변수를 두지 않고 점–평면 수직거리를 직접 최소화한다.
#   RANSAC 으로 요철·이상치를 배제한 뒤 inlier 에 PCA(전최소제곱)를 적용.
#
# 기존 fit_plane_ransac() 은 하위호환을 위해 그대로 둔다.

def fit_plane_tls_ransac(points_3d, threshold=0.005, max_trials=300,
                         seed=42, min_inliers=3, refine=True):
    """
    방향에 무관한 robust 평면 적합.

    Parameters
    ----------
    threshold : float — inlier 판정 점–평면 수직거리 (m)
    max_trials : int  — RANSAC 반복 (inlier 비율이 충분하면 조기 종료)

    Returns
    -------
    plane : (a, b, c, d)  정규화된 법선 + offset  (aX+bY+cZ+d = 0)
    inlier_mask : (N,) bool
    """
    pts = np.asarray(points_3d, dtype=float)
    N = len(pts)
    if N < 3:
        raise ValueError(f"평면 적합에 점이 부족합니다 (N={N} < 3)")

    rng = np.random.default_rng(seed)
    best_mask, best_cnt = None, 0
    for _ in range(int(max_trials)):
        p0, p1, p2 = pts[rng.choice(N, 3, replace=False)]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn < 1e-12:
            continue                       # 세 점이 거의 일직선
        n = n / nn
        mask = np.abs(pts @ n + (-np.dot(n, p0))) <= threshold
        cnt = int(mask.sum())
        if cnt > best_cnt:
            best_cnt, best_mask = cnt, mask
            if cnt > 0.95 * N:
                break                      # 충분히 좋음 → 조기 종료

    if best_mask is None or best_cnt < min_inliers:
        best_mask = np.ones(N, dtype=bool)  # 폴백: 전체로 TLS

    if refine:
        # inlier 에 PCA → 최소 특이값 방향이 법선 (전최소제곱 해)
        for _ in range(2):
            sel = pts[best_mask]
            c = sel.mean(axis=0)
            _, _, vt = np.linalg.svd(sel - c, full_matrices=False)
            n = vt[-1] / np.linalg.norm(vt[-1])
            d = -float(np.dot(n, c))
            new_mask = np.abs(pts @ n + d) <= threshold
            if new_mask.sum() < min_inliers:
                break
            best_mask = new_mask
    sel = pts[best_mask]
    c = sel.mean(axis=0)
    _, _, vt = np.linalg.svd(sel - c, full_matrices=False)
    n = vt[-1] / np.linalg.norm(vt[-1])
    d = -float(np.dot(n, c))
    return (float(n[0]), float(n[1]), float(n[2]), d), best_mask


# =====================================================================
# [v2 추가] 선형 부재(동바리·기둥·철근) 축 적합
# =====================================================================
# 동바리·철근은 평면이 아니라 1D 선형 부재이므로 평면적합이 성립하지 않는다.
# 표면 점군이 축 방향으로 길게 분포하는 성질을 이용해 PCA 1주성분을
# 부재 축으로 본다. 축 방향은 eq3.measure_axis_verticality() 로 넘긴다.
#
# 정확도 주의 (Ø48.6mm 파이프서포트 기준):
#   · 실루엣 가장자리 점은 시선이 원통에 스치듯 닿아 삼각측량이 부정확하다.
#     → 호출 전에 마스크를 침식(eq5_region_assign)해 가장자리를 제거할 것.
#   · 400 교점 중 얇은 파이프에 맞는 점은 소수이므로 최소 점수 게이트가 필요하다.
#   · 축 방향 분산이 횡방향 분산보다 충분히 크지 않으면(선형성 부족)
#     축 추정이 불안정하므로 linearity 로 함께 보고한다.

def fit_axis_pca(points_3d, min_points=8, min_linearity=0.80):
    """
    PCA 1주성분으로 선형 부재의 축 방향을 추정한다.

    Parameters
    ----------
    points_3d : (N, 3) — 부재 영역 점군 (m)
    min_points : int
        축 추정에 필요한 최소 점 수. 미만이면 is_valid=False.
    min_linearity : float
        선형성 하한. linearity = λ1 / (λ1+λ2+λ3) 로, 1에 가까울수록
        점군이 한 방향으로 곧게 뻗어 있음을 뜻한다.

    Returns
    -------
    dict
        direction    : (3,) 단위벡터 — 축 방향 (부호는 임의)
        centroid     : (3,) 축이 지나는 점
        length_m     : float — 축 방향 점군 길이 (KCS mm 판정용 부재 길이)
        radial_rms_mm: float — 축에서의 반경 방향 RMS (원통 반지름 + 노이즈)
        linearity    : float — λ1/(λ1+λ2+λ3)
        n_points     : int
        is_valid     : bool — 점 수·선형성 게이트 통과 여부
        reject_reason: str | None
    """
    pts = np.asarray(points_3d, dtype=float)
    out = {"direction": None, "centroid": None, "length_m": 0.0,
           "radial_rms_mm": 0.0, "linearity": 0.0,
           "n_points": int(len(pts)), "is_valid": False, "reject_reason": None}

    if len(pts) < min_points:
        out["reject_reason"] = f"점 부족 ({len(pts)} < {min_points})"
        return out

    centroid = pts.mean(axis=0)
    centered = pts - centroid
    # SVD 로 주성분 (공분산 고유분해와 동일하나 수치적으로 안정)
    _, sv, vt = np.linalg.svd(centered, full_matrices=False)
    eigvals = (sv ** 2) / max(len(pts) - 1, 1)
    direction = vt[0] / np.linalg.norm(vt[0])

    total = float(eigvals.sum())
    linearity = float(eigvals[0] / total) if total > 1e-18 else 0.0

    t = centered @ direction                      # 축 방향 좌표
    radial = centered - np.outer(t, direction)    # 축에서의 수직 성분
    radial_rms_mm = float(np.sqrt(np.mean(np.sum(radial ** 2, axis=1))) * 1000.0)

    out.update(direction=direction, centroid=centroid,
               length_m=float(t.max() - t.min()),
               radial_rms_mm=radial_rms_mm, linearity=linearity)

    if linearity < min_linearity:
        out["reject_reason"] = f"선형성 부족 (linearity {linearity:.3f} < {min_linearity})"
        return out

    out["is_valid"] = True
    return out


def plane_tangent_basis(plane_normal):
    """
    평면 법선으로부터 면내(in-plane) 정규직교 기저 (e1, e2) 를 만든다.

    평활도(eq4)는 점군을 격자로 비닝하는데, 조사기 좌표계의 X-Y로
    비닝하면 경사지게 보이는 면(예: 한 장에 같이 찍힌 바닥)에서 셀이
    찌그러진다. 면내 좌표로 비닝하면 시야각과 무관해져 KCS의
    "3m 직선자" 의미와 일치한다.

    Returns
    -------
    e1, e2 : (3,) 각각 법선에 수직이고 서로 직교하는 단위벡터
    """
    n = np.asarray(plane_normal, dtype=float)[:3]
    n = n / np.linalg.norm(n)
    # n 과 가장 덜 평행한 좌표축을 골라 특이점 회피
    seed = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(n, seed); e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1);   e2 /= np.linalg.norm(e2)
    return e1, e2


def project_to_plane_frame(points_3d, plane):
    """
    점군을 평면 국소 좌표계 (u, v, w) 로 변환한다.

    u, v : 면내 좌표 (m)      w : 평면으로부터의 부호 있는 이탈 (m)
    eq4 평활도 비닝과 eq6 가상 직선자가 이 좌표를 쓴다.

    Returns
    -------
    uvw : (N, 3),  basis : (e1, e2, n),  origin : (3,)
    """
    pts = np.asarray(points_3d, dtype=float)
    a, b, c, d = plane
    n = np.array([a, b, c], dtype=float)
    nn = np.linalg.norm(n); n = n / nn
    e1, e2 = plane_tangent_basis(n)
    origin = -(d / nn) * n                    # 원점에서 평면에 내린 발
    rel = pts - origin
    uvw = np.column_stack([rel @ e1, rel @ e2, rel @ n])
    return uvw, (e1, e2, n), origin
