#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspection.py — [품질검측] 현장 촬영 + 선검출(A) + 삼각측량(B) + eq 검증
========================================================================
실제 품질검측에서 매번 실행하는 메인 파이프라인.

흐름:
  씬 열기 + 카메라/레이저 세팅
  → 스테이션별 촬영
      레이저 위치 계산 (laser_pos, cam_pos, R)
      → IMU 기울기 주입 + 카메라 자세 세팅 (R_tilted, M44)
      → Raycast → GT 픽셀 + z_cam_m 저장
      → 발광 메시 렌더 → rgb_laser 획득
      → [A] detect()  → lines_pixels
      → 선 필터링 (불량선 제거)
      → IMU 픽셀 보정
      → data.json / rgb_raw.png / rgb_laser.png / overlay.png 저장
  → 3_pipeline_eq_verify.py 로 eq 검증

실행:
  python3 inspection.py
========================================================================
"""
import os, sys, json
import numpy as np

# =====================================================================
# 설정값 (캘리브레이션)
# =====================================================================
# 카메라: Daheng MER2-503-36U3C / 렌즈: 12mm F2.0 / 센서: Sony IMX264, 3.45μm
CAMERA_PARAMS = {
    "f_px":  1593.0,      # 원본 검증값 (렌더 정상 확인)
    "b_m":   0.150,       # baseline 150mm (용역서 고정)
    "cx_px": 1224.0,      # 센서 중앙 W/2
    "cy_px": 1024.0,      # 센서 중앙 H/2
    "resolution": [2448, 2048],
}
GRID_PARAMS = {
    # 20칸 × 20칸 격자 = 선 21개 × 21개
    # (칸 = 선 사이 공간이므로, N칸을 만들려면 선은 N+1개)
    "n_vertical":       21,     # DOE 수직선 (21선 → 20칸)
    "n_horizontal":     21,     # DOE 수평선 (21선 → 20칸)
    "fov_deg":          60.82,  # V선 전체 이미지 안 (50px 마진)
    "samples_per_line": 250,
}
STATIONS = {
    "StationA_Wall":  {"target": "/World/StationA/WallBackFace",
                       "normal": [0., -1., 0.], "inspect": "verticality",
                       "standoff_m": 1.0},
    "StationA_Floor": {"target": "/World/StationA/FloorTop",
                       "normal": [0.,  0., 1.], "inspect": "horizontality",
                       "standoff_m": 1.0},
    "StationB":       {"target": "/World/StationB/Panel",
                       "normal": [0., -1., 0.], "inspect": "flatness",
                       "standoff_m": 1.0},
}
SCENE_USD  = "/home/develop/Desktop/laser_grid_test_4/inspection_lab_realistic.usda"
GT_JSON    = "/home/develop/Desktop/laser_grid_test_4/inspection_ground_truth_realistic.json"
OUTPUT_DIR = "/home/develop/Desktop/laser_grid_test_4/result/realistic_dataset"

# =====================================================================
# A, B 알고리즘 import
# =====================================================================
import importlib.util as _ilu, os as _os

def _load_algo(path, func_name):
    spec = _ilu.spec_from_file_location("_algo", path)
    mod  = _ilu.module_from_spec(spec); spec.loader.exec_module(mod)
    return getattr(mod, func_name)

_HERE = _os.path.dirname(_os.path.abspath(__file__))
fn_detect = None  # 초기값, SimulationApp 이후 _init_algorithms()로 로드

def _init_algorithms():
    """SimulationApp 완전 초기화 후 A 알고리즘 로드. main()과 experiment 양쪽에서 호출."""
    global fn_detect
    if fn_detect is None:
        fn_detect = _load_algo(_os.path.join(_HERE, "A_선검출.py"), "detect")
    return fn_detect

# =====================================================================
# Isaac Sim import
# =====================================================================
_RUNNING_IN_GUI = False
try:
    import omni.usd
    if omni.usd.get_context().get_stage() is not None:
        _RUNNING_IN_GUI = True
except Exception:
    pass

if not _RUNNING_IN_GUI:
    from isaacsim import SimulationApp
    simulation_app = SimulationApp({"headless": False,
                                    "width": 2448, "height": 2048})

import omni.kit.app
try:
    import carb
    cs = carb.settings.get_settings()
    cs.set("/rtx/post/bloom/enabled",      False)
    cs.set("/rtx/post/lensFlares/enabled", False)
except Exception:
    pass

from pxr import Usd, UsdGeom, UsdPhysics, UsdShade, UsdLux, Gf, Sdf
from omni.isaac.core import World
from omni.isaac.core.utils.stage import open_stage, get_current_stage
from omni.isaac.sensor import Camera
from omni.physx import get_physx_scene_query_interface
try:
    import omni.replicator.core as rep  # noqa
except Exception:
    pass
from PIL import Image, ImageDraw  # SimulationApp 이후 안전하게 import


def LOG(msg): print(msg, flush=True)

# =====================================================================
# 유틸
# =====================================================================
def _norm(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _wait(world, n):
    for _ in range(n):
        if _RUNNING_IN_GUI: omni.kit.app.get_app().update()
        else:               world.step(render=True)


def _world_center_of(stage, path):
    p = stage.GetPrimAtPath(path)
    if not p or not p.IsValid(): return None
    try:
        bb  = UsdGeom.Imageable(p).ComputeWorldBound(
                Usd.TimeCode.Default(), UsdGeom.Tokens.default_)
        box = bb.ComputeAlignedBox()
        mn, mx = box.GetMin(), box.GetMax()
        if mn[0] <= mx[0]:
            return np.array([(mn[i]+mx[i])/2. for i in range(3)])
    except Exception:
        pass
    try:
        m = UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        t = m.ExtractTranslation()
        return np.array([t[0], t[1], t[2]])
    except Exception:
        return None


def _rotmat_to_quat(R):
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t+1.)*2; w=.25*s; x=(R[2,1]-R[1,2])/s; y=(R[0,2]-R[2,0])/s; z=(R[1,0]-R[0,1])/s
    elif R[0,0]>R[1,1] and R[0,0]>R[2,2]:
        s=np.sqrt(1.+R[0,0]-R[1,1]-R[2,2])*2; w=(R[2,1]-R[1,2])/s; x=.25*s; y=(R[0,1]+R[1,0])/s; z=(R[0,2]+R[2,0])/s
    elif R[1,1]>R[2,2]:
        s=np.sqrt(1.+R[1,1]-R[0,0]-R[2,2])*2; w=(R[0,2]-R[2,0])/s; x=(R[0,1]+R[1,0])/s; y=.25*s; z=(R[1,2]+R[2,1])/s
    else:
        s=np.sqrt(1.+R[2,2]-R[0,0]-R[1,1])*2; w=(R[1,0]-R[0,1])/s; x=(R[0,2]+R[2,0])/s; y=(R[1,2]+R[2,1])/s; z=.25*s
    return np.array([w,x,y,z])


def _device_tilt_from_R(R):
    f = R[:,2]; up = R[:,1]
    pitch = np.degrees(np.arcsin(np.clip(-f[2],-1,1)))
    roll  = np.degrees(np.arctan2(up[0],up[2])) if abs(up[2])>1e-9 else 0.
    return {"pitch_deg": float(pitch), "roll_deg": float(roll)}


def _simulate_imu(R_ideal, pitch_deg, roll_deg):
    p,r = np.radians(pitch_deg), np.radians(roll_deg)
    Rp = np.array([[1,0,0],[0,np.cos(p),-np.sin(p)],[0,np.sin(p),np.cos(p)]])
    Rr = np.array([[np.cos(r),0,np.sin(r)],[0,1,0],[-np.sin(r),0,np.cos(r)]])
    R_t = R_ideal @ (Rr @ Rp)
    g_l = R_t.T @ np.array([0.,0.,-1.])
    return R_t, {
        "measured_pitch_deg": float(np.degrees(np.arctan2(-g_l[1],-g_l[2]))),
        "measured_roll_deg":  float(np.degrees(np.arctan2( g_l[0],-g_l[2]))),
        "injected_pitch_deg": pitch_deg, "injected_roll_deg": roll_deg,
    }


def _correct_imu(lines_pixels, imu_data, cp):
    f,cx,cy = cp["f_px"],cp["cx_px"],cp["cy_px"]
    p = np.radians(imu_data["measured_pitch_deg"])
    r = np.radians(imu_data["measured_roll_deg"])
    Rp_i = np.array([[1,0,0],[0,np.cos(p),np.sin(p)],[0,-np.sin(p),np.cos(p)]])
    Rr_i = np.array([[np.cos(r),0,-np.sin(r)],[0,1,0],[np.sin(r),0,np.cos(r)]])
    K = np.array([[f,0,cx],[0,f,cy],[0,0,1]],float)
    H = K @ (Rp_i @ Rr_i) @ np.linalg.inv(K)
    out = {}
    for lid,pts in lines_pixels.items():
        if not pts: out[lid]=pts; continue
        arr=np.array(pts,float); uvh=np.hstack([arr,np.ones((len(arr),1))])
        c=(H@uvh.T).T; w=c[:,2:3]; w=np.where(np.abs(w)<1e-9,1e-9,w)
        out[lid]=(c[:,:2]/w).tolist()
    return out


def _filter_lines(lines_pixels, cp, min_pts=30, max_u_std=80., max_v_std=80.):
    W,H=cp["resolution"]; vV,vH,rej=[],[],{}
    for lid,pts in lines_pixels.items():
        arr=np.array(pts,float) if pts else np.zeros((0,2))
        if len(arr)<min_pts: rej[lid]=f"점수부족({len(arr)})"; continue
        ok=(arr[:,0]>=0)&(arr[:,0]<W)&(arr[:,1]>=0)&(arr[:,1]<H)
        if ok.mean()<0.5: rej[lid]="범위이탈"; continue
        if lid.startswith("V"):
            if np.std(arr[ok,0])>max_u_std: rej[lid]="V직선성불량"; continue
            vV.append(lid)
        elif lid.startswith("H"):
            if np.std(arr[ok,1])>max_v_std: rej[lid]="H직선성불량"; continue
            vH.append(lid)
    key=lambda l: int(l[1:]) if l[1:].isdigit() else 0
    return sorted(vV,key=key), sorted(vH,key=key), rej



def _set_lighting_intensity(stage, scale):
    """조명 강도를 scale 배로 조정 (0=끔, 1=원래)."""
    _BASE_INTENSITIES = {
        "/World/SunKey":     2500.0,
        "/World/AmbientFill": 400.0,
        "/World/SunFill":     900.0,
    }
    try:
        for path, base_val in _BASE_INTENSITIES.items():
            p = stage.GetPrimAtPath(path)
            if p and p.IsValid():
                p.GetAttribute("intensity").Set(float(base_val * scale))
    except Exception:
        pass

def _make_emissive_grid(stage, lines_world, normal):
    """
    산업용 520nm 레이저 선 렌더링.

    실제 Laserlands 20×20 DOE 520nm 레이저 특성:
      - 선폭: 벽면 1m 거리에서 약 0.5~0.8mm
        → 카메라(f=1593px, 1m) 기준 약 0.8~1.3px 로 맺힘
        → 3D 선폭: 0.0006m (0.6mm) 로 설정
      - 발광 강도: 90mW급 레이저, 벽면 반사 후 카메라 수광
        → emissiveScale 800~1200 (배경 조명 대비 압도적 밝기)
      - 색상: 순수 녹색 (R=0, G=1, B=0) — 520nm 단색광
        → emissiveColor (0, 1, 0), diffuseColor (0, 0, 0)
      - 레이저선은 자체 발광만, diffuse 반사 없음

    선폭이 좁아지면(0.6mm → ~1px):
      → 가우시안 피팅의 peak가 더 선명 → 서브픽셀 정밀도 향상
      → pixel_rmse 감소 → σZ 감소 기대
    """
    base="/World/LaserGrid"
    if stage.GetPrimAtPath(base).IsValid(): stage.RemovePrim(base)
    UsdGeom.Scope.Define(stage, base)
    mat = UsdShade.Material.Define(stage, base+"/GreenLaser")
    sh  = UsdShade.Shader.Define(stage,  base+"/GreenLaser/S")
    sh.CreateIdAttr("UsdPreviewSurface")

    # 순수 520nm 녹색 — R,B 성분 제거 (G-avg(R,B) 채널분리 효과 극대화)
    sh.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(0.0, 1.0, 0.0))
    # 산업용 레이저 밝기: 배경 조명(2500 lux 수준) 대비 압도적으로 밝게
    sh.CreateInput("emissiveScale", Sdf.ValueTypeNames.Float).Set(1000.0)
    # 레이저선 자체는 diffuse 반사 없음 (발광체)
    sh.CreateInput("diffuseColor",  Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(0.0, 0.0, 0.0))
    sh.CreateInput("roughness",     Sdf.ValueTypeNames.Float).Set(0.0)
    sh.CreateInput("metallic",      Sdf.ValueTypeNames.Float).Set(0.0)
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")

    nrm = np.asarray(normal, float)
    nrm /= max(np.linalg.norm(nrm), 1e-9)

    # 선폭: 0.6mm (실제 산업용 레이저 선폭)
    # 기존 5mm → 0.6mm: 카메라 상 ~8px → ~1px 로 좁아짐
    LASER_WIDTH_M = 0.0006

    n = 0
    for lid, pts in lines_world.items():
        if len(pts) < 2: continue
        # 벽면에서 살짝 띄워서 z-fighting 방지 (0.5mm)
        off = [P + nrm * 0.0005 for P in pts]
        cv  = UsdGeom.BasisCurves.Define(stage, f"{base}/{lid}")
        cv.CreateTypeAttr().Set("linear")
        cv.CreatePointsAttr(
            [Gf.Vec3f(float(p[0]), float(p[1]), float(p[2])) for p in off])
        cv.CreateCurveVertexCountsAttr([len(off)])
        cv.CreateWidthsAttr([LASER_WIDTH_M] * len(off))
        cv.SetWidthsInterpolation(UsdGeom.Tokens.vertex)
        UsdShade.MaterialBindingAPI(cv).Bind(mat)
        n += 1
    return n


def _setup_scene():
    """씬 열기 + 콜라이더 + 조명."""
    stage=get_current_stage()
    already=bool(stage and stage.GetPrimAtPath("/World/StationB").IsValid())
    if _RUNNING_IN_GUI and already:
        LOG("  GUI 현장 재사용")
    else:
        if not os.path.exists(SCENE_USD):
            raise FileNotFoundError(f"씬 없음: {SCENE_USD}")
        open_stage(SCENE_USD); stage=get_current_stage()

    try: world=World(stage_units_in_meters=1.)
    except Exception as e: LOG(f"  [경고] World: {e}"); world=None

    for p in stage.Traverse():
        if p.IsA(UsdGeom.Mesh):
            if not p.HasAPI(UsdPhysics.CollisionAPI):
                UsdPhysics.CollisionAPI.Apply(p)

    _boost_lighting(stage)
    return stage, world


def _boost_lighting(stage):
    """현실적 조명: 비스듬한 방향광(요철 입체감) + 앰비언트 + 보조광 (원본 동일)."""
    try:
        results = []
        # 1) 방향성 광원 — 비스듬히 내리쬐어 결함 요철이 명암으로 드러남
        dpath = "/World/SunKey"
        if not stage.GetPrimAtPath(dpath).IsValid():
            dist = UsdLux.DistantLight.Define(stage, dpath)
            dist.CreateIntensityAttr(2500.0)
            dist.CreateColorAttr(Gf.Vec3f(1.0, 0.97, 0.92))
            dist.CreateAngleAttr(1.0)
            xf = UsdGeom.Xformable(dist.GetPrim())
            xf.ClearXformOpOrder()
            xf.AddRotateXYZOp().Set(Gf.Vec3f(-35.0, 0.0, 25.0))
            results.append("DistantLight")
        # 2) 앰비언트 dome
        path = "/World/AmbientFill"
        if not stage.GetPrimAtPath(path).IsValid():
            dome = UsdLux.DomeLight.Define(stage, path)
            dome.CreateIntensityAttr(400.0)
            dome.CreateColorAttr(Gf.Vec3f(0.85, 0.88, 0.95))
            results.append("DomeLight")
        # 3) 보조 방향광
        dpath2 = "/World/SunFill"
        if not stage.GetPrimAtPath(dpath2).IsValid():
            d2 = UsdLux.DistantLight.Define(stage, dpath2)
            d2.CreateIntensityAttr(900.0)
            d2.CreateColorAttr(Gf.Vec3f(0.9, 0.93, 1.0))
            d2.CreateAngleAttr(2.0)
            xf2 = UsdGeom.Xformable(d2.GetPrim())
            xf2.ClearXformOpOrder()
            xf2.AddRotateXYZOp().Set(Gf.Vec3f(-20.0, 0.0, -40.0))
            results.append("FillLight")
        LOG(f"  조명: {', '.join(results)} 설치")
    except Exception as e:
        LOG(f"  [경고] 조명: {e}")


def _setup_camera(stage):
    """카메라 생성 + 핀홀 파라미터 세팅 (AP_MM=W_px → 1px=1mm → FOV 수식과 동일)."""
    W_px,H_px = CAMERA_PARAMS["resolution"]
    f_px = CAMERA_PARAMS["f_px"]
    cx_px,cy_px = CAMERA_PARAMS["cx_px"],CAMERA_PARAMS["cy_px"]

    UsdGeom.Xform.Define(stage,"/World/InspectionRig")
    cam=Camera(prim_path="/World/InspectionRig/InspectionCamera",
               resolution=(W_px,H_px))
    cam.initialize()

    # 원본 방식: ap=36mm 기준으로 fmm 역산 → FOV 정상 (F < AP)
    AP_MM = 36.0
    F_MM  = float(f_px) * AP_MM / float(W_px)   # = 51.15mm
    AP_V  = AP_MM * H_px / W_px                  # 세로 aperture
    try:
        cp=stage.GetPrimAtPath("/World/InspectionRig/InspectionCamera")
        uc=UsdGeom.Camera(cp)
        uc.GetFocalLengthAttr().Set(F_MM)
        uc.GetHorizontalApertureAttr().Set(AP_MM)
        uc.GetVerticalApertureAttr().Set(AP_V)
        uc.GetClippingRangeAttr().Set(Gf.Vec2f(0.01, 50.0))
    except Exception as e:
        LOG(f"  [경고] 카메라 파라미터: {e}")
    return cam


def _set_camera_xform(stage, R, cam_pos):
    """R 행렬로 카메라 자세 직접 세팅 (SetLookAt 미사용)."""
    cp=stage.GetPrimAtPath("/World/InspectionRig/InspectionCamera")
    M44=Gf.Matrix4d(
        float(R[0,0]),float(R[1,0]),float(R[2,0]),0.,
        float(R[0,1]),float(R[1,1]),float(R[2,1]),0.,
        float(R[0,2]),float(R[1,2]),float(R[2,2]),0.,
        float(cam_pos[0]),float(cam_pos[1]),float(cam_pos[2]),1.)
    xf=UsdGeom.Xformable(cp); xf.ClearXformOpOrder(); xf.AddTransformOp().Set(M44)


def _make_line_angles(n_v,n_h,fov_deg):
    fov=np.radians(fov_deg)
    va=np.linspace(-fov/2,fov/2,n_v); ha=np.linspace(-fov/2,fov/2,n_h)
    a={}
    for i,ang in enumerate(va): a[f"V{i}"]={"fixed":"alpha","angle_rad":float(ang)}
    for j,ang in enumerate(ha): a[f"H{j}"]={"fixed":"beta", "angle_rad":float(ang)}
    return a


# =====================================================================
# 핵심: 스테이션 촬영
# =====================================================================
def capture_station(stage, world, camera, line_angles,
                    station_name, cfg, gt_full,
                    baseline_m=None, standoff_m=None,
                    noise_sigma_px=0.0, output_dir=None,
                    use_diff_image=False):
    """
    한 스테이션(벽/바닥/패널)을 촬영하고 data.json + 이미지를 저장한다.

    Parameters
    ----------
    baseline_m    : float or None
        기선 거리(m). None이면 CAMERA_PARAMS["b_m"] 사용 (품질검측 기본값)
    standoff_m    : float or None
        측정 거리(m). None이면 cfg["standoff_m"] 사용 (품질검측 기본값)
    noise_sigma_px: float
        픽셀 Gaussian 노이즈 σ (실험용, 품질검측에서는 0.0)
    use_diff_image: bool
        [방안4] True면 차영상 모드. 레이저 ON 프레임과 OFF 프레임
        (조명만 켜진 배경)을 각각 캡처하여 A_선검출에 함께 전달한다.
        배경광이 상쇄되어 현장 직사광 환경에서 검출 강건성이 향상된다.

    흐름
    ----
    위치 계산 (laser_pos, cam_pos, R_laser)
    → IMU 기울기 주입 (R_tilted)
    → 카메라 xform 세팅 (R_tilted 직접)
    → Raycast → GT픽셀 + z_cam_m  [노이즈 주입]
    → rgb_raw 캡처
    → [차영상] 레이저 OFF 프레임 캡처 (조명 ON, 레이저 없음)
    → 발광 메시 렌더 → rgb_laser 캡처
    → [A] fn_detect(rgb_laser, laser_off=rgb_off) → lines_pixels
    → 선 필터링
    → IMU 픽셀 보정
    → data.json 저장
    → overlay.png 저장 (raycast 파랑 + 검출 초록)
    """
    cp = dict(CAMERA_PARAMS)
    # 실험에서 baseline 오버라이드
    if baseline_m is not None:
        cp["b_m"] = float(baseline_m)
    f, b, cx, cy = cp["f_px"], cp["b_m"], cp["cx_px"], cp["cy_px"]

    # 실험에서 standoff 오버라이드
    _standoff = standoff_m if standoff_m is not None else cfg.get("standoff_m", 1.0)

    # ── 위치 계산 ──
    center = _world_center_of(stage, cfg["target"])
    if center is None:
        LOG(f"  [건너뜀] {station_name}: prim 없음"); return None
    center += np.asarray(cfg.get("center_offset_m",[0.,0.,0.]),float)
    normal = _norm(cfg.get("normal",[0.,-1.,0.]))
    up     = np.array([0.,0.,1.])
    if abs(np.dot(normal,up))>0.95: up=np.array([0.,1.,0.])

    laser_center = center + normal * _standoff
    view_l  = _norm(center-laser_center)
    right_l = _norm(np.cross(view_l, up))   # SetLookAt과 동일한 right 방향
    up_l    = _norm(np.cross(view_l,right_l))
    R_laser  = np.column_stack([right_l,up_l,view_l])
    laser_pos= laser_center.copy()
    cam_pos  = laser_center + right_l*b
    R_ideal  = R_laser.copy()

    # IMU (현재는 이상적 자세로 촬영, 추후 활성화)
    imu_data = {"injected_pitch_deg":0., "injected_roll_deg":0.,
                "measured_pitch_deg":0., "measured_roll_deg":0.}

    # ── 카메라 xform 세팅: SetLookAt ──
    # Step1: lookat_up 결정 (view_l과 평행하면 특이점 방지)
    lookat_up = up.copy()
    if abs(np.dot(view_l, lookat_up)) > 0.9:
        lookat_up = np.array([0., 1., 0.])
        if abs(np.dot(view_l, lookat_up)) > 0.9:
            lookat_up = np.array([1., 0., 0.])

    # Step2: right_l을 SetLookAt과 완전히 일치하도록 재계산
    # SetLookAt 내부: right = cross(forward, up_hint) 후 정규화
    right_l = _norm(np.cross(view_l, lookat_up))
    up_l    = _norm(np.cross(view_l, right_l))
    R  = np.column_stack([right_l, up_l, view_l])
    Rt = R.T

    # Step3: cam_pos, tgt_pos를 재계산된 right_l로 확정
    cam_pos = laser_center + right_l * b
    tgt_pos = cam_pos + view_l   # 카메라 정면 (레이저와 평행)

    cam_prim = stage.GetPrimAtPath("/World/InspectionRig/InspectionCamera")
    M = Gf.Matrix4d().SetLookAt(
        Gf.Vec3d(float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2])),
        Gf.Vec3d(float(tgt_pos[0]), float(tgt_pos[1]), float(tgt_pos[2])),
        Gf.Vec3d(float(lookat_up[0]), float(lookat_up[1]), float(lookat_up[2]))
    ).GetInverse()
    xf = UsdGeom.Xformable(cam_prim)
    xf.ClearXformOpOrder()
    xf.AddTransformOp().Set(M)
    _wait(world, 15)

    # ── Raycast → GT 픽셀 + z_cam_m ──
    query   = get_physx_scene_query_interface()
    fov     = np.radians(GRID_PARAMS["fov_deg"])
    samples = np.linspace(-fov/2,fov/2,GRID_PARAMS["samples_per_line"])
    lines_pixels_raycast={};  ground_truth={};  lines_world={}
    n_hit=0

    for lid,info in line_angles.items():
        px_pts,gt_pts,w_pts=[],[],[]
        for s in samples:
            alpha = info["angle_rad"] if info["fixed"]=="alpha" else s
            beta  = info["angle_rad"] if info["fixed"]=="beta"  else s
            d_local=_norm([np.tan(alpha),np.tan(beta),1.])
            d_world=R_laser@d_local
            hit=query.raycast_closest(tuple(laser_pos),tuple(d_world),30.)
            if hit and hit["hit"]:
                P=np.array(hit["position"])
                p_cam=Rt@(P-cam_pos); Z=p_cam[2]
                if Z>1e-4:
                    u_i=f*p_cam[0]/Z+cx; v_i=f*p_cam[1]/Z+cy
                    # 실험용 노이즈 (품질검측에서는 noise_sigma_px=0.0)
                    if noise_sigma_px > 0:
                        u=u_i+float(np.random.normal(0,noise_sigma_px))
                        v=v_i+float(np.random.normal(0,noise_sigma_px))
                    else:
                        u,v=u_i,v_i
                    px_pts.append([float(u),float(v)])
                    gt_pts.append({"xyz":P.tolist(),
                                   "u_px":float(u),"v_px":float(v),
                                   "distance_m":float(np.linalg.norm(P-cam_pos)),
                                   "z_cam_m":float(Z)})
                    w_pts.append(P); n_hit+=1
        lines_pixels_raycast[lid]=px_pts
        ground_truth[lid]=gt_pts
        lines_world[lid]=w_pts

    if n_hit==0:
        LOG(f"  [건너뜀] {station_name}: raycast 적중 없음"); return None

    # ── rgb_raw 캡처 ──
    _wait(world,20)
    try: rgba=camera.get_rgba(); rgb_raw=rgba[:,:,:3] if rgba is not None else None
    except: rgb_raw=None

    # ── [방안4] 레이저 OFF 프레임 (차영상용) ──
    # rgb_raw가 이미 "조명 ON + 레이저 없음" 상태이므로 그대로 OFF 프레임으로
    # 사용한다. 차영상 모드에서는 아래 레이저 렌더도 조명을 켠 채 수행하여
    # ON/OFF 두 프레임의 조명 조건을 일치시킨다.
    rgb_off = rgb_raw if use_diff_image else None

    # ── 발광 메시 렌더 → rgb_laser ──
    # 일반 모드: 조명을 끄고 레이저만 촬영 (암실 모사, 배경광 없음)
    # [방안4] 차영상 모드: 조명을 켠 채로 레이저 촬영.
    #   ON(조명+레이저) − OFF(조명) 차분 시 배경광이 상쇄되어야 하므로
    #   두 프레임의 조명 조건이 반드시 동일해야 한다.
    rgb_laser=None
    try:
        if use_diff_image:
            # 차영상: 조명 유지 (OFF 프레임과 동일 조명 조건)
            _wait(world, 5)
        else:
            # 일반: 조명 강도를 0으로 (암실 모사)
            _set_lighting_intensity(stage, 0.0)
            _wait(world, 5)

        ng=_make_emissive_grid(stage,lines_world,normal)
        LOG(f"  발광 레이저 {ng}선"); _wait(world,60)
        rgba2=camera.get_rgba()
        rgb_laser=rgba2[:,:,:3] if rgba2 is not None else None
        if stage.GetPrimAtPath("/World/LaserGrid").IsValid():
            stage.RemovePrim("/World/LaserGrid")

        # 조명 복원 (일반 모드에서 껐을 경우)
        if not use_diff_image:
            _set_lighting_intensity(stage, 1.0)
            _wait(world, 5)
    except Exception as e:
        LOG(f"  [경고] 렌더: {e}")
        _set_lighting_intensity(stage, 1.0)

    # ── [A] 선검출 ──
    if fn_detect is None:
        _init_algorithms()
    # [방안4] 차영상 모드면 OFF 프레임 함께 전달 (배경광 제거)
    if rgb_laser is not None:
        try:
            if use_diff_image and rgb_off is not None:
                lines_pixels_detected = fn_detect(rgb_laser,
                                                  lines_pixels_raycast,
                                                  line_angles, cp,
                                                  laser_off_image=rgb_off)
            else:
                lines_pixels_detected = fn_detect(rgb_laser,
                                                  lines_pixels_raycast,
                                                  line_angles, cp)
        except TypeError:
            # 구버전 A_선검출 (laser_off_image 미지원) 폴백
            lines_pixels_detected = fn_detect(rgb_laser,
                                              lines_pixels_raycast,
                                              line_angles, cp)
    else:
        lines_pixels_detected = lines_pixels_raycast

    # ── 선 필터링 ──
    valid_V,valid_H,rejected=_filter_lines(lines_pixels_detected,cp)
    valid_ids=set(valid_V+valid_H)
    lines_filtered={k:v for k,v in lines_pixels_detected.items() if k in valid_ids}
    gt_filtered   ={k:v for k,v in ground_truth.items()          if k in valid_ids}
    if not valid_V:
        LOG(f"  [경고] 유효 V선 없음"); return None

    # ── IMU 픽셀 보정 ──
    lines_corrected=_correct_imu(lines_filtered,imu_data,cp)

    # ── GT 매핑 ──
    gt_station_key="StationA" if station_name.startswith("StationA") else station_name
    gt_station=gt_full.get("stations",{}).get(gt_station_key,{})
    inspect=cfg.get("inspect","flatness")
    surfaces=gt_station.get("surfaces",{})
    gt_tilt=None
    if   inspect=="verticality":   gt_tilt=surfaces.get("WallBack",{}).get("signal_tilt_deg")
    elif inspect=="horizontality": gt_tilt=surfaces.get("Floor",{}).get("signal_tilt_deg")
    sgt=(gt_station if inspect=="flatness"
         else {"role":inspect,"gt_tilt_deg":gt_tilt,"surface":surfaces})

    # ── data.json 저장 ──
    out={
        "station": station_name, "inspect": inspect, "scene_usd": SCENE_USD,
        "camera_world":{
            "position_m":cam_pos.tolist(),
            "laser_position_m":laser_pos.tolist(),
            "wall_center_m":center.tolist(),
            "quaternion_wxyz":_rotmat_to_quat(R).tolist(),
            "forward_dir":R[:,2].tolist(),
            "standoff_m":float(_standoff),
            "baseline_m":float(b),
            "normal":normal.tolist(),
        },
        "device_tilt":  _device_tilt_from_R(R),
        "imu":          imu_data,
        "camera_params": cp,
        "line_angles":   line_angles,
        "lines_pixels":  lines_corrected,       # IMU 보정 후 → eq 검증 입력
        "lines_pixels_raw": lines_pixels_raycast,  # raycast 참조
        "ground_truth":  gt_filtered,
        "scene_ground_truth": sgt,
        "quality":{"rays_hit":n_hit,
                   "rays_total":len(line_angles)*GRID_PARAMS["samples_per_line"],
                   "valid_V":len(valid_V),"rejected":len(rejected)},
    }
    _out_base = output_dir if output_dir is not None else OUTPUT_DIR
    out_dir=os.path.join(_out_base,station_name)
    os.makedirs(out_dir,exist_ok=True)
    with open(os.path.join(out_dir,"data.json"),"w",encoding="utf-8") as fp:
        json.dump(out,fp,ensure_ascii=False,indent=2)

    # ── 이미지 저장 ──
    _save_images(out_dir, rgb_raw, rgb_laser,
                 lines_corrected, lines_pixels_raycast,
                 rgb_off=rgb_off)

    LOG(f"  {station_name}: 적중 {n_hit}  유효V {len(valid_V)}  "
        f"기각 {len(rejected)}  → {out_dir}")
    return out


def _save_images(out_dir, rgb_raw, rgb_laser,
                 lines_detected, lines_raycast, rgb_off=None):
    """rgb_raw / rgb_laser / rgb_off / overlay 저장."""
    try:
        if rgb_raw is not None:
            Image.fromarray(rgb_raw).save(os.path.join(out_dir,"rgb_raw.png"))
        if rgb_laser is not None:
            Image.fromarray(rgb_laser).save(os.path.join(out_dir,"rgb_laser.png"))
        # [방안4] 차영상 OFF 프레임 저장 (있을 때만)
        if rgb_off is not None:
            Image.fromarray(rgb_off).save(os.path.join(out_dir,"rgb_off.png"))

        base=rgb_laser if rgb_laser is not None else rgb_raw
        if base is None: return
        im=Image.fromarray(base).convert("RGB")
        W,H=im.size; dr=ImageDraw.Draw(im)
        for lid,pts in lines_raycast.items():
            xy=[(float(p[0]),float(p[1])) for p in pts
                if -10<=p[0]<W+10 and -10<=p[1]<H+10]
            if len(xy)>=2: dr.line(xy,fill=(0,80,255),width=2)   # 파랑: raycast 참값
        for lid,pts in lines_detected.items():
            xy=[(float(p[0]),float(p[1])) for p in pts
                if -10<=p[0]<W+10 and -10<=p[1]<H+10]
            if len(xy)>=2: dr.line(xy,fill=(40,230,70),width=2)  # 초록: A 검출
        im.save(os.path.join(out_dir,"overlay.png"))
    except Exception as e:
        LOG(f"  [경고] 이미지저장: {e}")


# =====================================================================
# 메인
# =====================================================================
def main():
    _init_algorithms()
    LOG("="*60)
    LOG("품질검측 파이프라인 시작")
    LOG("="*60)

    gt_full={}
    if os.path.exists(GT_JSON):
        with open(GT_JSON,encoding="utf-8") as fp: gt_full=json.load(fp)
    else:
        LOG(f"[경고] GT 없음: {GT_JSON}")

    stage,world=_setup_scene()
    try: world.reset()
    except Exception: pass

    os.makedirs(OUTPUT_DIR,exist_ok=True)
    from PIL import Image as _PIL
    tex_path=os.path.join(OUTPUT_DIR,"_grid_tex.png")
    img=np.zeros((2048,2048,3),dtype=np.uint8)
    nv,nh=GRID_PARAMS["n_vertical"],GRID_PARAMS["n_horizontal"]
    for i in range(nv): x=int(2048*(i+.5)/nv); img[:,max(0,x-3):x+3]=255
    for j in range(nh): y=int(2048*(j+.5)/nh); img[max(0,y-3):y+3,:]=255
    _PIL.fromarray(img).save(tex_path)

    camera=_setup_camera(stage)
    line_angles=_make_line_angles(GRID_PARAMS["n_vertical"],
                                  GRID_PARAMS["n_horizontal"],
                                  GRID_PARAMS["fov_deg"])

    _wait(world,30)

    results={}
    for name,cfg in STATIONS.items():
        LOG(f"\n── {name} ──")
        r=capture_station(stage,world,camera,line_angles,name,cfg,gt_full)
        if r: results[name]={"hit":r["quality"]["rays_hit"]}

    with open(os.path.join(OUTPUT_DIR,"metadata.json"),"w",encoding="utf-8") as fp:
        json.dump({"scene":SCENE_USD,"camera_params":CAMERA_PARAMS,
                   "stations":list(STATIONS.keys()),"results":results},
                  fp,ensure_ascii=False,indent=2)

    LOG(f"\n완료 → {OUTPUT_DIR}")
    LOG("다음: python3 3_pipeline_eq_verify.py <data.json> [모드]")


if __name__=="__main__":
    main()
