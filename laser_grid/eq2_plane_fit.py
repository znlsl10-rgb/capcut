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
