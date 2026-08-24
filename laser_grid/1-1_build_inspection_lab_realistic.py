#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
현장 리얼리즘 강건성 테스트 버전.
깨끗한 버전(inspection_lab.usda)과 동일한 tilt/결함 정답값 위에,
'방해요소'를 덮어 line_detect / eq1~6 의 강건성을 검증한다.

방해요소 (전부 정답과 분리해서 GT에 기록):
  기하: 거푸집 이음선(2mm 홈), 미세요철(~0.6mm), 폼타이 구멍(4mm), 균열
  시각: 절차적 콘크리트 텍스처(얼룩/물자국/골재 반점) → Isaac RTX에서 렌더
  씬  : 잔재 더미, 비계 발판, 팔레트, 기둥 상단 철근, 강한 작업등 그림자

좌표계/단위: 깨끗한 버전과 동일 (Z-up, meter).
출력: inspection_lab_realistic.usda + concrete_diffuse.png + concrete_rough.png
      + inspection_ground_truth_realistic.json
"""
import json
import numpy as np
from PIL import Image

# pxr(USD) 라이브러리 경로 확보를 위해 SimulationApp 먼저 기동 (headless)
try:
    from pxr import Usd  # noqa  - 이미 경로 잡혀있으면 그대로
except ModuleNotFoundError:
    from isaacsim import SimulationApp
    _sim_app = SimulationApp({"headless": True})
from pxr import Usd, UsdGeom, UsdShade, Sdf, Gf, UsdLux


def gaussian_filter(arr, sigma):
    """scipy.ndimage.gaussian_filter 대체 (numpy FFT). sigma는 스칼라 또는 (sy,sx)."""
    arr = np.asarray(arr, float)
    if np.isscalar(sigma):
        sy = sx = float(sigma)
    else:
        sy, sx = float(sigma[0]), float(sigma[1])
    ny, nx = arr.shape
    fy = np.fft.fftfreq(ny).reshape(-1, 1)
    fx = np.fft.fftfreq(nx).reshape(1, -1)
    # 주파수영역 가우시안 (sigma 픽셀 → 주파수 감쇠)
    gy = np.exp(-2 * (np.pi * sy * fy) ** 2)
    gx = np.exp(-2 * (np.pi * sx * fx) ** 2)
    out = np.fft.ifft2(np.fft.fft2(arr) * (gy * gx)).real
    return out

OUT_USD = "inspection_lab_realistic.usda"
OUT_GT = "inspection_ground_truth_realistic.json"
DIFF_PNG, ROUGH_PNG = "concrete_diffuse.png", "concrete_rough.png"
HEIGHTMAP_PNG = "inspection_heightmap.png"
RES = 0.005


def save_heightmap(defects, sig_field, detail_field, PW, PH, res=480):
    """패널 결함 높이맵을 CLEAN/REALISTIC/NUISANCE 3-패널 PNG로 저장."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    U, V = np.meshgrid(np.linspace(0, PW, res), np.linspace(0, PH, int(res*PH/PW)))
    Zclean = sig_field(U, V) * 1000.0            # 결함만 (mm)
    Zdetail = detail_field(U, V) * 1000.0        # 방해요소만 (mm)
    Zreal = Zclean + Zdetail                     # 합성
    vmax = max(8.0, np.abs(Zclean).max())
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    panels = [(Zclean, "CLEAN: defects only"),
              (Zreal, "REALISTIC: defects + nuisance"),
              (Zdetail, "NUISANCE only (seams/tie/micro)")]
    for ax, (Z, title) in zip(axes, panels):
        im = ax.imshow(Z, extent=[0, PW, 0, PH], origin="lower",
                       cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
        ax.set_title(title); ax.set_xlabel("U (m)"); ax.set_ylabel("V (m)")
        plt.colorbar(im, ax=ax, label="mm")
    n_b = sum(1 for d in defects if d["amp"] > 0)
    n_d = sum(1 for d in defects if d["amp"] < 0)
    fig.suptitle(f"StationB Panel height map  |  defects: {len(defects)} "
                 f"(bump {n_b}, dent {n_d})  range [{Zclean.min():.1f},{Zclean.max():.1f}]mm",
                 y=1.02)
    plt.tight_layout()
    plt.savefig(HEIGHTMAP_PNG, dpi=110, bbox_inches="tight")
    plt.close()
    print(f"높이맵 저장: {HEIGHTMAP_PNG}")


# ---------------------------------------------------------------------------
# 1) 절차적 콘크리트 텍스처
# ---------------------------------------------------------------------------
def make_concrete_textures(size=1024, seed=7):
    rng = np.random.default_rng(seed)
    base = np.full((size, size), 0.58)
    # 큰 얼룩 (색 변화) - 대비 강화
    stains = gaussian_filter(rng.standard_normal((size, size)), 45)
    stains = (stains - stains.min()) / np.ptp(stains)
    base += (stains - 0.5) * 0.22                                   # 얼룩 강화 0.14→0.22
    # 중간 얼룩 (추가 레이어)
    blot = gaussian_filter(rng.standard_normal((size, size)), 12)
    blot = (blot - blot.min()) / np.ptp(blot)
    base += (blot - 0.5) * 0.12
    # 물 흘러내린 자국
    streak = gaussian_filter(rng.standard_normal((size, size)), (70, 5))
    base += np.clip(streak, None, 0) * 0.14
    # 골재 반점 (거칠게 - sigma 낮추고 가중치 키움)
    speck = gaussian_filter(rng.standard_normal((size, size)), 1.2)
    base += speck * 0.10                                            # 0.05→0.10
    # 미세 표면 노이즈 (콘크리트 까끌함)
    micro = rng.standard_normal((size, size))
    base += micro * 0.025
    # 작은 공극(에어포켓) - 어두운 점들
    pores = rng.random((size, size))
    base -= (pores > 0.995) * 0.15
    # 거푸집 가로 이음선
    for y in np.linspace(0, size, 6)[1:-1]:
        yy = int(y)
        base[max(0, yy - 2):yy + 2, :] -= 0.12
    base = np.clip(base, 0.28, 0.85)
    tint = np.stack([base * 1.00, base * 0.985, base * 0.95], -1)   # 약한 회갈색
    Image.fromarray((np.clip(tint, 0, 1) * 255).astype(np.uint8)).save(DIFF_PNG)
    rough = np.clip(0.80 + speck * 0.15 + (stains - 0.5) * 0.08 + micro * 0.03, 0.45, 0.98)
    Image.fromarray((rough * 255).astype(np.uint8)).save(ROUGH_PNG)


# ---------------------------------------------------------------------------
# 2) 기하학적 방해요소 height field
# ---------------------------------------------------------------------------
def concrete_detail(U, V, seed, seam_spacing=0.6, seam_depth=0.002,
                    micro=0.0006, tie_spacing=0.9, tie_depth=0.004, crack=None):
    Z = np.zeros_like(U)
    d = np.minimum(U % seam_spacing, seam_spacing - (U % seam_spacing))
    Z -= seam_depth * np.exp(-(d ** 2) / (2 * 0.005 ** 2))          # 세로 이음선 홈
    rng = np.random.default_rng(seed)
    for _ in range(6):                                             # 미세요철(대역제한)
        fx, fy = rng.uniform(3, 14, 2)
        Z += (micro / 6) * np.sin(2 * np.pi * (fx * U + fy * V) + rng.uniform(0, 2 * np.pi))
    umax, vmax = U.max(), V.max()
    for ix in np.arange(tie_spacing / 2, umax, tie_spacing):        # 폼타이 구멍
        for iy in np.arange(tie_spacing / 2, vmax, tie_spacing):
            Z -= tie_depth * np.exp(-(((U - ix) ** 2 + (V - iy) ** 2) / (2 * 0.012 ** 2)))
    if crack:                                                      # 균열(폴리라인)
        for (x0, y0), (x1, y1) in zip(crack[:-1], crack[1:]):
            px, py = x1 - x0, y1 - y0
            L2 = px * px + py * py + 1e-9
            t = np.clip(((U - x0) * px + (V - y0) * py) / L2, 0, 1)
            dx, dy = U - (x0 + t * px), V - (y0 + t * py)
            dist = np.sqrt(dx * dx + dy * dy)
            Z -= 0.003 * np.exp(-(dist ** 2) / (2 * 0.004 ** 2))
    return Z


# ---------------------------------------------------------------------------
# 재질
# ---------------------------------------------------------------------------
def solid_material(stage, path, albedo, rough=0.85):
    mat = UsdShade.Material.Define(stage, path)
    sh = UsdShade.Shader.Define(stage, path + "/S")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*albedo))
    sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(rough)
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    return mat


def textured_material(stage, path):
    mat = UsdShade.Material.Define(stage, path)
    reader = UsdShade.Shader.Define(stage, path + "/stReader")
    reader.CreateIdAttr("UsdPrimvarReader_float2")
    reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    diff = UsdShade.Shader.Define(stage, path + "/diffTex")
    diff.CreateIdAttr("UsdUVTexture")
    diff.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(DIFF_PNG)      # 상대경로
    diff.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), "result")
    diff.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("repeat")
    diff.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("repeat")
    rgh = UsdShade.Shader.Define(stage, path + "/roughTex")
    rgh.CreateIdAttr("UsdUVTexture")
    rgh.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(ROUGH_PNG)
    rgh.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), "result")
    surf = UsdShade.Shader.Define(stage, path + "/S")
    surf.CreateIdAttr("UsdPreviewSurface")
    surf.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(diff.ConnectableAPI(), "rgb")
    surf.CreateInput("roughness", Sdf.ValueTypeNames.Float).ConnectToSource(rgh.ConnectableAPI(), "r")
    mat.CreateSurfaceOutput().ConnectToSource(surf.ConnectableAPI(), "surface")
    return mat


# ---------------------------------------------------------------------------
# 솔리드 박스 (clutter/backing/column 용)
# ---------------------------------------------------------------------------
def add_box(stage, path, size, translate, rotate_xyz, material, inspn=(0, 0, 1)):
    sx, sy, sz = size
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    pts = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
           (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
    faces = [4, 5, 6, 7, 0, 3, 2, 1, 0, 1, 5, 4, 2, 3, 7, 6, 1, 2, 6, 5, 0, 4, 7, 3]
    m = UsdGeom.Mesh.Define(stage, path)
    m.CreatePointsAttr([Gf.Vec3f(*p) for p in pts])
    m.CreateFaceVertexCountsAttr([4] * 6)
    m.CreateFaceVertexIndicesAttr(faces)
    m.CreateSubdivisionSchemeAttr().Set(UsdGeom.Tokens.none)
    # UV: 각 면을 0..1로 (텍스처 입히기 위함). 면당 4정점 × 6면 = 24
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)] * 6
    pvapi = UsdGeom.PrimvarsAPI(m)
    st = pvapi.CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray,
                             UsdGeom.Tokens.faceVarying)
    st.Set([Gf.Vec2f(*uv) for uv in uvs])
    xf = UsdGeom.Xformable(m)
    xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    xf.AddRotateXYZOp().Set(Gf.Vec3f(*rotate_xyz))
    UsdShade.MaterialBindingAPI(m).Bind(material)
    M = np.array(UsdGeom.Imageable(m).ComputeLocalToWorldTransform(Usd.TimeCode.Default()))
    n = np.array(inspn, float) @ M[:3, :3]
    return [round(float(v), 6) for v in (n / np.linalg.norm(n))]


# ---------------------------------------------------------------------------
# 테셀레이션 검측면 (signal_field + 방해요소, UV 포함, 텍스처)
# ---------------------------------------------------------------------------
def add_textured_surface(stage, path, width, height, signal_field, detail_field,
                         translate, rotate_xyz, material):
    nx = int(round(width / RES)) + 1
    ny = int(round(height / RES)) + 1
    xs, ys = np.linspace(0, width, nx), np.linspace(0, height, ny)
    U, V = np.meshgrid(xs, ys, indexing="xy")
    Zsig = signal_field(U, V) if signal_field else np.zeros_like(U)
    Zdet = detail_field(U, V) if detail_field else np.zeros_like(U)
    Z = Zsig + Zdet
    pts = np.stack([U.ravel(), V.ravel(), Z.ravel()], 1)
    st = np.stack([(U / width).ravel(), (V / height).ravel()], 1)
    counts, idx = [], []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            counts.append(4)
            idx.extend([a, a + 1, a + nx + 1, a + nx])
    m = UsdGeom.Mesh.Define(stage, path)
    m.CreatePointsAttr([Gf.Vec3f(*p) for p in pts.astype(float)])
    m.CreateFaceVertexCountsAttr(counts)
    m.CreateFaceVertexIndicesAttr(idx)
    m.CreateSubdivisionSchemeAttr().Set(UsdGeom.Tokens.none)
    pv = UsdGeom.PrimvarsAPI(m).CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray,
                                              UsdGeom.Tokens.vertex)
    pv.Set([Gf.Vec2f(*s) for s in st.astype(float)])
    xf = UsdGeom.Xformable(m)
    xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    xf.AddRotateXYZOp().Set(Gf.Vec3f(*rotate_xyz))
    UsdShade.MaterialBindingAPI(m).Bind(material)
    M = np.array(UsdGeom.Imageable(m).ComputeLocalToWorldTransform(Usd.TimeCode.Default()))
    n = np.array([0, 0, 1.0]) @ M[:3, :3]
    return [round(float(v), 6) for v in (n / np.linalg.norm(n))], (nx, ny)


def add_anchor(stage, path, t, r):
    x = UsdGeom.Xformable(UsdGeom.Xform.Define(stage, path))
    x.AddTranslateOp().Set(Gf.Vec3d(*t))
    x.AddRotateXYZOp().Set(Gf.Vec3f(*r))
    return {"translate": list(t), "rotate_xyz_deg": list(r)}


def add_rebar(stage, path, base, h=0.4, r=0.008, tilt=8):
    c = UsdGeom.Cylinder.Define(stage, path)
    c.CreateHeightAttr(h)
    c.CreateRadiusAttr(r)
    c.CreateAxisAttr("Z")
    xf = UsdGeom.Xformable(c)
    xf.AddTranslateOp().Set(Gf.Vec3d(*base))
    xf.AddRotateXYZOp().Set(Gf.Vec3f(tilt, 0, 0))


# ---------------------------------------------------------------------------
def main():
    make_concrete_textures()
    stage = Usd.Stage.CreateNew(OUT_USD)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/World").GetPrim())

    # --- 조명: 두 station 작업등 + 비스듬한 방향광(결함 입체감) + 약한 ambient ---
    UsdLux.DomeLight.Define(stage, "/World/Lights/Dome").CreateIntensityAttr(300.0)
    # StationA 작업등
    workA = UsdLux.RectLight.Define(stage, "/World/Lights/WorkLightA")
    workA.CreateIntensityAttr(9000.0); workA.CreateWidthAttr(0.6); workA.CreateHeightAttr(0.6)
    UsdGeom.Xformable(workA).AddTranslateOp().Set(Gf.Vec3d(2.5, -1.2, 2.6))
    UsdGeom.Xformable(workA).AddRotateXYZOp().Set(Gf.Vec3f(-115, 0, 0))
    # StationB(Panel x≈11) 작업등 — 비스듬히 위옆에서 → 결함 요철이 명암으로
    workB = UsdLux.RectLight.Define(stage, "/World/Lights/WorkLightB")
    workB.CreateIntensityAttr(9000.0); workB.CreateWidthAttr(0.6); workB.CreateHeightAttr(0.6)
    UsdGeom.Xformable(workB).AddTranslateOp().Set(Gf.Vec3d(10.7, 3.0, 2.0))
    UsdGeom.Xformable(workB).AddRotateXYZOp().Set(Gf.Vec3f(-115, 0, 25))
    # StationA 바닥(Floor, Z=0) 작업등 — 카메라 뒤 위쪽에서 비스듬히 → 그림자 없이 바닥 밝게
    workF = UsdLux.RectLight.Define(stage, "/World/Lights/WorkLightFloor")
    workF.CreateIntensityAttr(15000.0); workF.CreateWidthAttr(1.2); workF.CreateHeightAttr(1.2)
    UsdGeom.Xformable(workF).AddTranslateOp().Set(Gf.Vec3d(3.3, 2.5, 2.2))
    UsdGeom.Xformable(workF).AddRotateXYZOp().Set(Gf.Vec3f(-70, 0, 0))  # 비스듬히 아래로
    # 바닥 보조 DomeLight 효과용 추가 작업등 (반대편)
    workF2 = UsdLux.RectLight.Define(stage, "/World/Lights/WorkLightFloor2")
    workF2.CreateIntensityAttr(8000.0); workF2.CreateWidthAttr(1.0); workF2.CreateHeightAttr(1.0)
    UsdGeom.Xformable(workF2).AddTranslateOp().Set(Gf.Vec3d(1.7, 2.5, 2.0))
    UsdGeom.Xformable(workF2).AddRotateXYZOp().Set(Gf.Vec3f(-110, 0, 0))
    # 전역 방향광(창 역광)
    win = UsdLux.DistantLight.Define(stage, "/World/Lights/Window")
    win.CreateIntensityAttr(1800.0); win.CreateAngleAttr(1.0)
    UsdGeom.Xformable(win).AddRotateXYZOp().Set(Gf.Vec3f(-25, 0, -110))

    tex = textured_material(stage, "/World/Looks/ConcreteTex")
    solid = solid_material(stage, "/World/Looks/ConcreteSolid", (0.58, 0.57, 0.55))
    rebar_mat = solid_material(stage, "/World/Looks/Rebar", (0.42, 0.30, 0.22), 0.6)
    wood = solid_material(stage, "/World/Looks/Wood", (0.55, 0.42, 0.26), 0.7)

    gt = {"units": "meter, deg", "up_axis": "Z", "note": "tilt/결함=신호, detail=방해요소",
          "stations": {}}

    HORIZ, VBACK = 0.3, 0.5
    # ===== Station A : 수직수평 (방해요소 덮음) =====
    A = {"role": "verticality_horizontality", "surfaces": {}}

    # Floor: 수평 기준(top@Z=0). 신호=tilt(xform). detail=가벼운 요철만(이음선 없음)
    fn, _ = add_textured_surface(
        stage, "/World/StationA/FloorTop", 5.0, 5.0,
        signal_field=None,
        detail_field=lambda U, V: concrete_detail(U, V, seed=11, seam_spacing=99,
                                                  seam_depth=0, micro=0.0008,
                                                  tie_spacing=99, tie_depth=0),
        translate=(0, 0, 0), rotate_xyz=(HORIZ, 0, 0), material=tex)
    add_box(stage, "/World/StationA/FloorSlab", (5.0, 5.0, 0.15),
            (2.5, 2.5, -0.075), (HORIZ, 0, 0), solid)
    A["surfaces"]["Floor"] = {"role": "horizontal_reference", "signal_tilt_deg": HORIZ,
                              "world_normal": fn,
                              "nuisance": {"micro_mm": 0.8}}

    # WallBack: 수직 기준 + 풀 방해요소. 검측면 세워서(+90X) 정면 -Y, tilt는 추가
    crack = [(0.4, 0.2), (0.9, 1.1), (1.3, 2.2), (1.1, 2.9)]
    wn, _ = add_textured_surface(
        stage, "/World/StationA/WallBackFace", 5.0, 3.0,
        signal_field=None,
        detail_field=lambda U, V: concrete_detail(U, V, seed=23, seam_spacing=0.6,
                                                  seam_depth=0.002, micro=0.0007,
                                                  tie_spacing=0.9, tie_depth=0.004,
                                                  crack=crack),
        translate=(0, 0, 0), rotate_xyz=(90 + VBACK, 0, 0), material=tex)
    add_box(stage, "/World/StationA/WallBackSlab", (5.0, 0.2, 3.0),
            (2.5, 0.11, 1.5), (VBACK, 0, 0), solid)
    A["surfaces"]["WallBack"] = {"role": "vertical_reference", "signal_tilt_deg": VBACK,
                                 "world_normal": wn,
                                 "nuisance": {"seam_spacing_m": 0.6, "seam_depth_mm": 2.0,
                                              "micro_mm": 0.7, "tie_depth_mm": 4.0,
                                              "crack": True}}

    # 수직도·수평도 검사는 넓고 평탄한 면을 보는 것이므로,
    # 검사를 방해하는 기둥/철근/잔재/팔레트/발판은 두지 않는다.
    # (현실의 결함·노이즈 검증은 평활도 StationB에서 수행)
    A["camera_anchor"] = add_anchor(stage, "/World/StationA/CamAnchor",
                                    (2.0, 2.0, 1.5), (0, 0, -135))
    gt["stations"]["StationA"] = A

    # ===== Station B : 평활도 (현실적 소형 결함 다수) =====
    BX, PW, PH = 10.0, 2.4, 1.8
    # 1m 격자가 보는 패널 중심부(U 0.7~1.7, V 0.4~1.4)에 작은 결함을 무작위 배치
    _rng = np.random.default_rng(2026)
    defects = []
    # (a) 작은 돌출 (자갈/혹): 지름 2~8cm, 높이 2~8mm  - 12개
    for i in range(12):
        u = float(_rng.uniform(0.7, 1.7)); v = float(_rng.uniform(0.4, 1.4))
        amp = float(_rng.uniform(0.002, 0.008))
        sig = float(_rng.uniform(0.01, 0.04))   # sigma 1~4cm → 지름 4~16cm
        defects.append({"label": f"bump_{i}", "center": (u, v), "amp": amp, "sigma": sig})
    # (b) 작은 함몰 (기포/곰보): 지름 1~5cm, 깊이 2~6mm - 8개
    for i in range(8):
        u = float(_rng.uniform(0.7, 1.7)); v = float(_rng.uniform(0.4, 1.4))
        amp = -float(_rng.uniform(0.002, 0.006))
        sig = float(_rng.uniform(0.008, 0.025))  # sigma 0.8~2.5cm → 지름 3~10cm
        defects.append({"label": f"dent_{i}", "center": (u, v), "amp": amp, "sigma": sig})
    # (c) 들뜸/박리 (조금 넓음): 지름 10~20cm, 높이 3~8mm - 3개
    for i in range(3):
        u = float(_rng.uniform(0.8, 1.6)); v = float(_rng.uniform(0.5, 1.3))
        amp = float(_rng.uniform(0.003, 0.008))
        sig = float(_rng.uniform(0.04, 0.06))   # sigma 4~6cm → 지름 16~24cm
        defects.append({"label": f"delam_{i}", "center": (u, v), "amp": amp, "sigma": sig})

    def sig_panel(U, V):
        Z = np.zeros_like(U)
        for d in defects:
            cx, cy = d["center"]
            Z += d["amp"] * np.exp(-(((U - cx) ** 2 + (V - cy) ** 2) / (2 * d["sigma"] ** 2)))
        return Z

    pn, _ = add_textured_surface(
        stage, "/World/StationB/Panel", PW, PH,
        signal_field=sig_panel,
        detail_field=lambda U, V: concrete_detail(U, V, seed=31, seam_spacing=0.6,
                                                  seam_depth=0.0015, micro=0.0006,
                                                  tie_spacing=1.2, tie_depth=0.003),
        translate=(BX, 4.0, 0.2), rotate_xyz=(90, 0, 0), material=tex)
    add_box(stage, "/World/StationB/Backing", (PW + 0.3, 0.15, PH + 0.3),
            (BX + PW / 2, 4.1, 0.2 + PH / 2), (0, 0, 0), solid)
    gt["stations"]["StationB"] = {
        "role": "flatness", "panel_size_m": [PW, PH], "world_normal": pn, "baseline_m": 0.5,
        "signal_defects_mm": [{"label": d["label"], "local_center_m": list(d["center"]),
                               "amp_mm": d["amp"] * 1000.0} for d in defects],
        "nuisance": {"seam_spacing_m": 0.6, "seam_depth_mm": 1.5, "micro_mm": 0.6,
                     "tie_depth_mm": 3.0},
        "camera_anchor": add_anchor(stage, "/World/StationB/CamAnchor",
                                    (BX + PW / 2, 3.5, 0.2 + PH / 2), (0, 0, 0))}

    # ===== 결함 높이맵 시각화 (CLEAN / REALISTIC / NUISANCE) =====
    try:
        save_heightmap(defects, sig_panel,
                       lambda U, V: concrete_detail(U, V, seed=31, seam_spacing=0.6,
                                                    seam_depth=0.0015, micro=0.0006,
                                                    tie_spacing=1.2, tie_depth=0.003),
                       PW, PH)
    except Exception as e:
        print(f"[경고] 히트맵 저장 실패: {e}")

    stage.GetRootLayer().Save()
    with open(OUT_GT, "w", encoding="utf-8") as f:
        json.dump(gt, f, ensure_ascii=False, indent=2)
    print("PRIMS:", sum(1 for _ in stage.Traverse()))
    print("Floor n=", gt["stations"]["StationA"]["surfaces"]["Floor"]["world_normal"])
    print("WallBack n=", gt["stations"]["StationA"]["surfaces"]["WallBack"]["world_normal"])
    print("Panel n=", gt["stations"]["StationB"]["world_normal"])


if __name__ == "__main__":
    main()
    try:
        _sim_app.close()
    except Exception:
        pass
