const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  PageBreak, LevelFormat, convertInchesToTwip, TableLayoutType,
} = require("docx");
const fs = require("fs");

const FONT = "맑은 고딕";
const MONO = "D2Coding";           // 없으면 시스템 대체 (Consolas 계열)
const MONO_FB = "Consolas";
const CW = 9638;                    // A4 - 좌우 여백 각 2cm

const C = {
  ink: "1A1D21", ink2: "44505A", ink3: "77848D",
  rule: "C4CDD4", head: "E8EDF0", accent: "0F6E33", warn: "9A5B0B",
};

/* ---------- helpers ---------- */
const P = (text, o = {}) => new Paragraph({
  spacing: { before: o.before ?? 0, after: o.after ?? 120, line: 300 },
  alignment: o.align,
  indent: o.indent,
  children: [new TextRun({
    text, font: o.mono ? MONO : FONT, size: o.size ?? 20,
    bold: o.bold, italics: o.italic, color: o.color ?? C.ink,
  })],
});

const Rich = (runs, o = {}) => new Paragraph({
  spacing: { before: o.before ?? 0, after: o.after ?? 120, line: 300 },
  indent: o.indent,
  children: runs.map(r => new TextRun({
    text: r.t, font: r.mono ? MONO : FONT, size: r.size ?? 20,
    bold: r.b, italics: r.i, color: r.c ?? C.ink,
  })),
});

const H1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 360, after: 200 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.rule, space: 6 } },
  children: [new TextRun({ text, font: FONT, size: 28, bold: true, color: C.ink })],
});

const H2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 260, after: 140 },
  children: [new TextRun({ text, font: FONT, size: 23, bold: true, color: C.ink })],
});

const H3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  spacing: { before: 200, after: 110 },
  children: [new TextRun({ text, font: FONT, size: 21, bold: true, color: C.ink2 })],
});

const Bul = (text, lvl = 0) => new Paragraph({
  numbering: { reference: "bul", level: lvl },
  spacing: { after: 90, line: 300 },
  children: [new TextRun({ text, font: FONT, size: 20, color: C.ink })],
});

const Code = (lines) => lines.map((l, i) => new Paragraph({
  spacing: { before: i === 0 ? 90 : 0, after: i === lines.length - 1 ? 150 : 0, line: 250 },
  shading: { type: ShadingType.CLEAR, fill: "F2F5F7" },
  indent: { left: 220, right: 220 },
  children: [new TextRun({ text: l || " ", font: MONO, size: 17, color: C.ink })],
}));

const Note = (text) => new Paragraph({
  spacing: { before: 120, after: 160, line: 300 },
  indent: { left: 200 },
  border: { left: { style: BorderStyle.SINGLE, size: 14, color: C.warn, space: 10 } },
  children: [new TextRun({ text, font: FONT, size: 19, color: C.ink2 })],
});

function Tbl(headers, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const scale = CW / total;
  const w = widths.map(x => Math.round(x * scale));
  const cell = (txt, i, isHead, mono, color) => new TableCell({
    width: { size: w[i], type: WidthType.DXA },
    shading: isHead ? { type: ShadingType.CLEAR, fill: C.head } : undefined,
    margins: { top: 70, bottom: 70, left: 110, right: 110 },
    children: String(txt).split(" ").map((line, k) => new Paragraph({
      spacing: { after: 0, line: 260 },
      children: [new TextRun({
        text: line, font: mono ? MONO : FONT, size: isHead ? 18 : 18,
        bold: isHead, color: color ?? (isHead ? C.ink : C.ink),
      })],
    })),
  });
  return new Table({
    width: { size: CW, type: WidthType.DXA },
    columnWidths: w,
    layout: TableLayoutType.FIXED,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 6, color: C.rule },
      bottom: { style: BorderStyle.SINGLE, size: 6, color: C.rule },
      left: { style: BorderStyle.SINGLE, size: 6, color: C.rule },
      right: { style: BorderStyle.SINGLE, size: 6, color: C.rule },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 4, color: C.rule },
      insideVertical: { style: BorderStyle.SINGLE, size: 4, color: C.rule },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((h, i) => cell(h, i, true)),
      }),
      ...rows.map(r => new TableRow({
        children: r.map((cv, i) => {
          const isObj = cv && typeof cv === "object" && !Array.isArray(cv);
          return cell(isObj ? cv.t : cv, i, false, isObj ? cv.mono : false,
                      isObj ? cv.c : undefined);
        }),
      })),
    ],
  });
}
const Gap = (h = 120) => new Paragraph({ spacing: { after: h }, children: [] });
const M = (t) => ({ t, mono: true });

/* ================= 본문 ================= */
const body = [];

/* ---------- 표지 ---------- */
body.push(
  new Paragraph({ spacing: { before: 1800, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "레이저 그리드 기반 현장 품질검측 장비",
      font: FONT, size: 26, color: C.ink2 })] }),
  new Paragraph({ spacing: { before: 160, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "영역별 품질검측 파이프라인",
      font: FONT, size: 48, bold: true, color: C.ink })] }),
  new Paragraph({ spacing: { before: 100, after: 500 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "구조 · 파라미터 · 입력 데이터 정리",
      font: FONT, size: 30, color: C.ink2 })] }),
  new Paragraph({ spacing: { before: 0, after: 0 }, alignment: AlignmentType.CENTER,
    border: { top: { style: BorderStyle.SINGLE, size: 8, color: C.rule, space: 14 } },
    children: [new TextRun({ text: " ", font: FONT, size: 20 })] }),
  new Paragraph({ spacing: { before: 300, after: 60 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "광운대학교 건설시스템공학 연구실",
      font: FONT, size: 22, color: C.ink })] }),
  new Paragraph({ spacing: { after: 60 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "저장소 znlsl10-rgb/capcut  ·  브랜치 claude/laser-image-segmentation-smoothness-yklpvp",
      font: MONO, size: 16, color: C.ink3 })] }),
  new Paragraph({ spacing: { after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "2026-08-25 기준  ·  Python 16개 파일, 8,145줄",
      font: FONT, size: 18, color: C.ink3 })] }),
  new Paragraph({ children: [new PageBreak()] }),
);

/* ================= 1. 개요 ================= */
body.push(H1("1. 개요"));

body.push(H2("1.1 목적"));
body.push(P("본 문서는 레이저 그리드 품질검측 장비의 소프트웨어를 「스테이션 단위 검측」에서 「영역 단위 검측」으로 전환한 작업을 정리한 것이다. 현장 사진 한 장에 벽·바닥·동바리·철근이 함께 들어와도, 영역을 나누어 각 부재에 맞는 검측식을 적용하는 것이 목표다."));

body.push(H2("1.2 기존 구조의 한계"));
body.push(P("기존 파이프라인은 검측 대상과 검측 항목을 설정 파일(STATIONS 딕셔너리)에 미리 적어두고, 화면 전체를 하나의 평면으로 적합했다. 즉 「무엇을 잴 것인가」가 인지 결과가 아니라 설정값이었다. 이 구조에서는 다음이 성립하지 않는다."));
body.push(Bul("한 장에 벽과 바닥이 같이 들어오면 두 면 사이 어딘가로 평면이 잡힌다."));
body.push(Bul("동바리·철근은 1D 선형 부재라 평면 적합 자체가 성립하지 않는다."));
body.push(Bul("수직도와 수평도가 서로 다른 좌표축(n_y / n_z)을 읽고 있어, 장비를 각 면에 정면으로 겨눈다는 전제에서만 옳다."));

body.push(H2("1.3 변경의 핵심"));
body.push(P("구조 변경의 실체는 「무엇을 잴지 정하는 신호」의 출처가 설정 파일에서 이미지로 옮겨온 것 하나이며, 나머지는 전부 그 결과다."));
body.push(Gap(60));
body.push(Tbl(
  ["구분", "기존 — 스테이션 단위", "지금 — 영역 단위"],
  [
    ["검측 대상 결정", "설정 파일(STATIONS)에 사전 기재", "세그멘테이션 결과에서 결정"],
    ["평면 가정", "화면 전체 = 단일 평면", "영역별 개별 적합"],
    ["기준 좌표계", "조사기 좌표계 축 고정", "중력벡터 ĝ 기준 통합"],
    ["부재 종류", "면(평면)만", "면 + 선형 부재(축)"],
    ["출력", "검측값 1개", "영역별 검측값 N개 + 판정"],
  ],
  [1700, 3900, 4038]));

/* ================= 2. 전체 구조 ================= */
body.push(H1("2. 전체 구조 및 데이터 흐름"));

body.push(H2("2.1 처리 흐름"));
body.push(P("1회 촬영은 레이저 ON/OFF 두 프레임으로 갈라진다. 레이저가 켜진 프레임은 격자선이 화면을 덮어 세그멘테이션을 방해하므로, 영역 분할은 OFF 프레임이 맡고 선검출만 ON 프레임을 쓴다. 두 프레임은 수십 µs 간격이라 마스크가 픽셀 단위로 그대로 정합되며, 이 방식은 차영상 모드를 위해 이미 하드웨어 사양에 있으므로 추가 촬영 비용이 없다."));
body.push(...Code([
  "1회 촬영  =  (rgb_off, rgb_on, IMU ĝ, 캘리브레이션)",
  "",
  "  ├─[A ] 선검출        rgb_on  → {lid: [(u,v)…]}",
  "  ├─[C ] 영역분할      rgb_off → label_map (H×W 클래스 id)",
  "  ├─[eq1] 삼각측량             → (X,Y,Z) 조사기 좌표계",
  "  ├─[eq5] 영역 할당            → 마스크 침식 · 깊이 불연속 제거",
  "  │                              의미×기하 융합 · 병합영역 재분할",
  "  └─ 영역별 검측",
  "       면 부재   (벽·바닥·거푸집·조적·슬래브)",
  "           eq2 평면 적합(TLS) → eq3 수직도/수평도",
  "                              → eq4 요철위치 + eq6 KCS 직선자",
  "       선형 부재 (동바리·기둥·철근)",
  "           eq2 축 적합(RANSAC) → eq3 축 수직도   [평활도 없음]",
  "",
  "       전 영역 → eq5 불확실도 → 합격 / 기준초과 /",
  "                                 측정불가 / 판정보류(분해능)",
]));
body.push(Note("벽과 바닥은 서로 다른 검측이 아니라 같은 식에 중력 ĝ만 다르게 들어가는 것이다. 실제로 갈라지는 지점은 「면이냐 축이냐」이며, 이는 부재의 기하 형상에 따른 구분이다."));

body.push(H2("2.2 파일 구성"));
body.push(P("계산 로직은 전부 Isaac Sim에 의존하지 않는 모듈에 두었다. 렌더링 없이도 같은 코드로 정답 대조가 가능하며, Isaac 쪽은 씬 구성과 촬영·렌더만 담당한다."));
body.push(Gap(60));
body.push(Tbl(
  ["단계", "파일", "역할"],
  [
    ["씬·촬영 (Isaac)", M("1-1_build_inspection_lab_realistic.py"),
     "USD 씬 + Semantics 라벨 부여. Replicator 어노테이터가 화소별 정답 마스크를 제공. StationC_Mixed = 벽+바닥+동바리 3본+철근 2본"],
    ["", M("inspection.py"), "촬영 → 선검출 → 시맨틱 마스크 → 영역별 검측. inspect=\"auto\"면 검측 종류를 세그멘테이션이 결정"],
    ["인지", M("A_선검출.py"), "20×20 격자 선검출. multi_surface로 단일 평면 가정 해제"],
    ["", M("C_영역분할.py"), "gt(Isaac Semantics)·geom(다중평면 RANSAC) 구현. sam·vlm은 인터페이스만"],
    ["검측식", M("eq1_triangulation.py"), "능동 삼각측량"],
    ["", M("eq2_plane_fit.py"), "TLS 평면적합, PCA·RANSAC 축적합, 면내 좌표계"],
    ["", M("eq3_orientation.py"), "중력 기준 수직·수평·축 수직도, KCS 판정"],
    ["", M("eq4_flatness_line.py"), "요철 위치·깊이 (면내 격자)"],
    ["", M("eq5_region_assign.py"), "영역 할당, 경계 정제, 의미×기하 융합, 불확실도"],
    ["", M("eq6_straightedge.py"), "KCS 직선자 판정 + 분해능 편향 진단"],
    ["통합·출력", M("pipeline_region.py"), "영역별 검측 오케스트레이션 (Isaac 비의존)"],
    ["", M("report.py"), "검측 조서(JSON)·요약표·영역 오버레이"],
    ["검증", M("synth_scene.py"), "벽+바닥+동바리 해석적 합성 씬 (카메라 가림 포함)"],
    ["", M("experiment_segmentation.py"), "세그멘테이션 오차 분해 실험"],
    ["", M("experiment.py"), "기선 × 측정거리 sweep (Isaac)"],
    ["", M("tests/test_regression.py"), "8군 회귀 검증"],
  ],
  [1200, 3100, 5338]));

/* ================= 3. 알고리즘 ================= */
body.push(new Paragraph({ children: [new PageBreak()] }));
body.push(H1("3. 품질검측 알고리즘"));

body.push(H2("3.1 식 ① 능동 삼각측량"));
body.push(...Code([
  "Z(i,j) = f·b / [ f·tan(α_i) − (u(i,j) − c_x) ]",
  "X(i,j) = (u − c_x)·Z/f + b",
  "Y(i,j) = (v − c_y)·Z/f",
]));
body.push(P("좌표계는 조사기 기준이며 X는 우측, Y는 하단(이미지 v 증가 방향), Z는 전방(작업거리)이다. 기선 b가 X축 방향이므로 시차는 u 좌표에만 실린다. 따라서 깊이를 풀려면 그 점의 발사각 α를 알아야 하고, α가 선마다 고정된 V선만 단독으로 삼각측량이 가능하다. H선은 β만 고정이고 α가 점마다 다르며, v 좌표는 이미 아는 tan(β)를 되풀이할 뿐이라 깊이 정보를 담지 않는다. H선은 V선과의 교점에서만 α를 회복할 수 있고, 그 교점은 이미 V선 조밀 샘플에 포함된다."));

body.push(H2("3.2 식 ②③ 자세 — 중력 기준 통합"));
body.push(P("기존 v1은 조사기 좌표계의 특정 축을 직접 읽었다. 벽은 arcsin(|n_y|), 바닥은 arccos(|n_z|)로 서로 다른 축을 썼는데, 이는 장비를 각 검측면에 정면으로 겨눈다는 전제에서만 성립한다. 한 장에 벽과 바닥이 동시에 들어오면 두 면에 대해 동시에 정면일 수 없으므로 이 전제가 깨진다."));
body.push(P("축을 고정하지 않고 중력벡터 ĝ를 명시적으로 받도록 일반화하였다."));
body.push(...Code([
  "벽    (면)  θ_vert  = arcsin |n̂ · ĝ|      완전 수직 → 0°",
  "바닥  (면)  θ_horiz = arccos |n̂ · ĝ|      완전 수평 → 0°",
  "동바리(축)  θ_vert  = arccos |d̂ · ĝ|      완전 수직 → 0°",
]));
body.push(P("기존 식은 이 일반식의 특수해다. ĝ=(0,1,0)이면 arcsin|n̂·ĝ| = arcsin|n_y|이고, ĝ=(0,0,1)이면 arccos|n̂·ĝ| = arccos|n_z|가 되어 v1과 수치적으로 동일하다. 따라서 기존 검증값(수직도 오차 0.0008°, 수평도 오차 0°)이 그대로 재현된다."));
body.push(Note("작업 중 확인: v1의 수평도 자체검증이 88°(참값 2°)로 이미 실패 상태였다. 벽과 바닥에서 서로 다른 축을 읽던 좌표계 가정이 원인이며, 중력 기준으로 통합하자 구조적으로 해소되었다."));
body.push(P("선형 부재(동바리·기둥·철근)는 평면이 아니므로 법선이 아니라 축 방향 d̂를 쓴다. 축은 PCA 1주성분으로 구하되, 얇은 부재는 마스크 실루엣에서 반드시 오염되므로 RANSAC 기반 robust 적합을 기본으로 한다. 또한 세그멘테이션이 부재의 3D 실제 길이를 주므로, 각도뿐 아니라 KCS가 규정하는 mm 편차(편차 = h·tanθ) 판정이 가능해진다."));

body.push(H2("3.3 식 ④ 요철 검출"));
body.push(P("영역 평면의 접선 기저로 좌표변환한 뒤 면내 (u,v) 격자에서 국소 median으로 노이즈를 억제하고, 임계 초과 후보를 DBSCAN으로 공간 검증하여 요철 클러스터를 확정한다. 요철 깊이는 평활값이 아니라 정점 근방 원시 잔차의 median에서 산출한다. 평활은 검출용 노이즈 억제 수단이며, 창이 요철보다 넓으면 깊이를 그만큼 깎기 때문이다."));

body.push(H2("3.4 식 ⑤ 영역 할당 및 불확실도"));
body.push(P("세그멘테이션이 준 픽셀 라벨맵과 삼각측량이 준 3D 점을 결합해 검측 단위인 영역을 만든다. 다음 네 가지를 수행한다."));
body.push(Bul("마스크 침식 — 경계 근처 격자점은 마스크 부정확·서브픽셀 혼합·실루엣 삼각측량 오차가 겹치므로 제외한다."));
body.push(Bul("깊이 불연속 제거 — 선을 따라 Z가 급변하는 지점의 양옆 점을 제거한다."));
body.push(Bul("의미×기하 융합 — 벽/바닥 구분과 면/선형 구분은 기하가 우선하고, 동바리·기둥·철근 구분과 벽·거푸집·조적 구분은 의미(라벨)가 우선한다. 기하가 구분할 수 없는 축은 라벨을 신뢰하는 비대칭 규칙이다."));
body.push(Bul("병합 영역 재분할 — 세그멘테이션이 두 부재를 같은 라벨로 묶으면 영역 적합이 두 면에 걸쳐 소수쪽 부재가 사라진다. 영역 내부 기하 부정합을 검사해 되쪼갠다."));
body.push(Gap(60));
body.push(P("불확실도는 다음과 같이 산출한다."));
body.push(...Code([
  "σ_Z = σ_u · Z² / (f · b)              깊이 방향",
  "σ_n = σ_Z / |cos φ|                   법선 방향 (φ = 입사각)",
]));
body.push(P("같은 사진 안에서도 정면인 벽은 φ≈0이라 σ_n≈σ_Z이지만, 비스듬히 들어온 바닥은 φ가 커져 σ_n이 크게 증폭된다. 평활도는 법선 방향 오차가 곧 측정치이므로 이 증폭을 반영해야 판정이 정직해진다. σ_n이 목표(±2mm)를 넘으면 값은 참고로 남기되 판정은 하지 않는다."));

body.push(H2("3.5 식 ⑥ KCS 직선자 평활도"));
body.push(P("기존 평활도는 전역 평면 잔차였으나 KCS가 규정하는 판정값은 그것이 아니다. KCS 14 20 10은 「3m 직선자에 의한 처짐량」, KCS 41 46 00은 1m당 10mm로, 현장 검사원이 자를 얹고 자와 표면 사이의 틈을 재는 값이다. 두 값은 다음과 같이 다르다."));
body.push(Gap(60));
body.push(Tbl(
  ["조건", "eq4 전역 평면 잔차", "eq6 3m 직선자 처짐"],
  [
    ["전역 휨 12mm (완만)", "7.90 mm", "0.54 mm"],
    ["국소 융기 6mm (급함)", "0.72 mm", "4.67 mm"],
  ],
  [3400, 3100, 3138]));
body.push(P("따라서 eq4 잔차로는 합격·불합격을 말할 수 없다. eq4는 요철의 위치를 찾는 데 쓰고, 시방 판정은 eq6이 담당한다.", { before: 140 }));
body.push(P("구간 안에서 자가 닿는 자리는 프로파일의 상부 볼록껍질이며, 처짐량은 그 껍질과 표면 사이 최대 간격이다. 이 정의는 볼록한 돌출과 오목한 함몰을 모두 물리적으로 맞게 다룬다."));
body.push(Note("분해능 편향 진단: 요철 폭이 평활 반경보다 좁으면 처짐량이 반드시 낮게 나온다. 이는 점 밀도의 물리적 한계이나, 기준초과를 합격으로 내보내는 방향이라 위험하다(실측: GT 8mm 융기 → 처짐 5.6mm → 허용 7mm 대비 거짓 합격). 평활을 촘촘히/성기게 두 번 걸어 결과 차이를 편향 추정치로 쓰고, 편향을 더해 허용치를 넘으면 「판정보류(분해능)」로 내보내 거짓 합격을 막는다."));

/* ================= 4. 입력 데이터 ================= */
body.push(new Paragraph({ children: [new PageBreak()] }));
body.push(H1("4. 사양 식에 들어가는 입력 데이터"));
body.push(P("검측 알고리즘이 동작하려면 하드웨어가 정해진 데이터를 정확히 제공해야 한다. 데이터는 매 촬영마다 보내는 것(A)과, 출고 시 1회 측정하여 모듈에 저장 후 전달하는 캘리브레이션(B)으로 나뉜다. B의 정확도가 곧 측정 정확도다."));

body.push(H2("4.1 매 촬영 데이터 (A)"));
body.push(Tbl(
  ["데이터", "기호", "용도", "현재 상태"],
  [
    ["격자점 픽셀 좌표", M("u, v"), "삼각측량 입력. A_선검출 출력", "런타임"],
    ["IMU 중력벡터", M("ĝ"), "수직·수평도 기준(중력)", { t: "미주입 — 자세별 기본값 사용", c: C.warn }],
    ["RGB 영상 (ON/OFF)", M("rgb_on/off"), "선검출 / 세그멘테이션", "런타임"],
  ],
  [2500, 1300, 3200, 2638]));

body.push(H2("4.2 캘리브레이션 데이터 (B)"));
body.push(Tbl(
  ["데이터", "기호", "용도", "현재 값", "상태"],
  [
    ["카메라 초점거리", M("f"), "삼각측량 기본 파라미터", M("1593.0 px"), { t: "시뮬 튜닝값", c: C.warn }],
    ["주점", M("c_x, c_y"), "영상 중심 좌표", M("1224.0, 1024.0"), { t: "센서 중앙 가정", c: C.warn }],
    ["기선", M("b"), "카메라–레이저 실측 간격", M("0.150 m"), "설계 고정값"],
    ["레이저 발사각 (V선)", M("α_i"), "중심축에서 i번째 격자선까지 꺾인 각", M("등각도 21분할"), { t: "가정값", c: C.warn }],
    ["레이저 발사각 (H선)", M("β_j"), "동일", M("등각도 21분할"), { t: "가정값", c: C.warn }],
    ["카메라–레이저 상대자세", M("R, t"), "두 광학계의 기하 관계", M("R=I, t=(b,0,0)"), { t: "가정값", c: C.warn }],
    ["IMU–카메라 상대자세", M("R_ic"), "IMU 자세를 카메라 좌표로 변환", M("단위행렬"), { t: "미구현", c: C.warn }],
    ["가속도계 bias", M("b_a"), "중력벡터 정밀도 보정", M("—"), { t: "미구현", c: C.warn }],
    ["선검출 픽셀 오차", M("σ_u"), "불확실도 산정 (σ_Z 식)", M("0.2 px"), { t: "가정값", c: C.warn }],
  ],
  [2300, 1150, 2650, 1900, 1638]));
body.push(Note("매 촬영마다 필요한 것은 u·v와 IMU ĝ 둘뿐이고, 나머지는 전부 출고 시 1회 캘리브레이션 값이다. 그중 실측에 기반한 것은 기선 b=150mm 하나이며, f·c_x·c_y는 시뮬레이션 튜닝값, α_i·β_j·R·t·R_ic는 가정값이다."));

body.push(H2("4.3 함수별 필수 입력 (코드 기준)"));
body.push(Tbl(
  ["식", "함수", "필수 입력", "주요 기본값"],
  [
    ["①", M("eq1.triangulate_point"), M("u, v, alpha, beta, f, b, cx, cy"), "없음 (전부 필수)"],
    ["②", M("eq2.fit_plane_tls_ransac"), M("points_3d"), M("threshold=0.005 m max_trials=300")],
    ["②", M("eq2.fit_axis_ransac"), M("points_3d"), M("radius_m=0.06 min_inlier_frac=0.45")],
    ["③", M("eq3.measure_from_gravity"), M("vec, g_hat, kind"), "없음"],
    ["③", M("eq3.gravity_in_laser_frame"), M("g_imu"), M("R_ic=None, R_cl=None (둘 다 단위행렬)")],
    ["④", M("eq4.detect_defects_region"), M("points_3d"), M("threshold_mm=1.5 grid_n=24, window='auto'")],
    ["⑤", M("eq5.region_uncertainty"), M("points_3d, camera_params"), M("sigma_u_px=0.2 target_sigma_mm=2.0")],
    ["⑥", M("eq6.straightedge_gap"), M("points_3d"), M("length_m=3.0 n_directions=4")],
  ],
  [700, 3000, 3000, 2938]));

/* ================= 5. 파라미터 ================= */
body.push(new Paragraph({ children: [new PageBreak()] }));
body.push(H1("5. 현재 파라미터 설정값"));

body.push(H2("5.1 캘리브레이션 상수"));
body.push(P("inspection.py — CAMERA_PARAMS", { mono: true, size: 17, color: C.ink3, after: 60 }));
body.push(...Code([
  "f_px       = 1593.0        # \"원본 검증값 (렌더 정상 확인)\"",
  "b_m        = 0.150         # \"baseline 150mm (용역서 고정)\"",
  "cx_px      = 1224.0        # \"센서 중앙 W/2\"   ← 측정 아님",
  "cy_px      = 1024.0        # \"센서 중앙 H/2\"   ← 측정 아님",
  "resolution = [2448, 2048]",
]));

body.push(H2("5.2 격자 및 발사각"));
body.push(P("inspection.py — GRID_PARAMS", { mono: true, size: 17, color: C.ink3, after: 60 }));
body.push(...Code([
  "n_vertical       = 21      # PDF 사양은 20 (400교점)",
  "n_horizontal     = 21",
  "fov_deg          = 60.82   # \"V선 전체 이미지 안 (50px 마진)\"",
  "samples_per_line = 250",
]));
body.push(P("발사각은 _make_line_angles()가 fov를 균등 분할해 생성한다. 실제로 계산되는 값은 다음과 같다.", { before: 100 }));
body.push(...Code([
  "α0 =-30.410°  α1 =-27.369°  α2 =-24.328°  α3 =-21.287°",
  "α4 =-18.246°  α5 =-15.205°  α6 =-12.164°  α7 = -9.123°",
  "α8 = -6.082°  α9 = -3.041°  α10=  0.000°  α11=  3.041°",
  "α12=  6.082°  α13=  9.123°  α14= 12.164°  α15= 15.205°",
  "α16= 18.246°  α17= 21.287°  α18= 24.328°  α19= 27.369°",
  "α20= 30.410°",
  "",
  "간격 일정 3.0410°  (등각도 가정).  β_j 도 동일한 값",
]));
body.push(Note("이것이 가장 취약한 값이다. PDF 3.1은 「i=0~20 각각 다른 α_i 가 DOE 제조 시 이미 고정」이라고 명시하는데, 코드는 균등 분할로 생성해 쓰고 있다. DOE 회절은 sinθ_m = m·λ/d 를 따라 등각도가 아니라 등 sin(각)에 가까우므로, 외곽선일수록 이 가정이 벌어진다. 출고 전 실측값으로 대체해야 한다."));

body.push(H2("5.3 판정 기준"));
body.push(H3("수직·수평도 — eq3.KCS_SPEC"));
body.push(Tbl(
  ["부재 분류", "tol_mm", "tol_ratio", "tol_deg"],
  [
    ["wall / column / shoring / rebar", "20.0", "1/1000 (권장 병기)", "0.5"],
    ["formwork / floor / slab", "20.0", "—", "0.5"],
    ["masonry", "10.0", "—", "0.5"],
  ],
  [4200, 1600, 2200, 1638]));
body.push(P("h/1000은 PDF 표에서 「층고대비 권장」으로 병기된 값이므로 본판정을 덮어쓰지 않고 권장기준으로만 함께 보고한다.", { before: 100, size: 18, color: C.ink2 }));

body.push(H3("평활도 직선자 — eq6.KCS_FLATNESS_SPEC"));
body.push(Tbl(
  ["부재 분류", "직선자 길이 · 허용 처짐량", "근거"],
  [
    ["wall / formwork_wall / formwork_column", "3.0 m · 7.0 mm", "KCS 14 20 10"],
    ["plaster_wall / masonry", "1.0 m · 10.0 mm", "KCS 41 46 00"],
    ["floor / slab", "1.0 m · 10.0 mm 및 3.0 m · 10.0 mm", "KCS 14 20 10"],
    ["ceiling", "3.0 m · 3.0 mm", "KCS 41 52 00"],
  ],
  [3600, 3800, 2238]));

body.push(H2("5.4 알고리즘 튜닝값"));
body.push(...Code([
  "eq5  erode_default_px      3       마스크 침식 (면)",
  "     erode_thin_px         1       마스크 침식 (동바리·철근)",
  "     min_points           12       영역 최소 점 수",
  "     jump_ratio         0.05       깊이 불연속 상대 임계",
  "     min_jump_m         0.02 m     깊이 불연속 절대 하한",
  "     linear_ratio       0.15       λ2/λ1 — 선형 판정",
  "     planar_ratio       0.15       λ3/λ2 — 평면 판정",
  "     thin_extent_m      0.12 m     선형 부재 최대 횡폭",
  "     align_deg          30.0       중력 정렬 허용각",
  "     min_thickness_ratio 0.02      λ3/λ2 — 판 vs 원통 판별",
  "",
  "eq2  plane threshold     0.005 m   TLS RANSAC inlier",
  "     axis radius_m       0.06 m    축 주변 inlier 반경",
  "     min_inlier_frac     0.45      축 적합 유효 하한",
  "",
  "eq4  threshold_mm        1.5       요철 판정 임계",
  "     grid_n              24        면내 격자 분할 수",
  "     window            'auto'      평활 창 자동 결정",
  "",
  "eq6  n_directions        4         자를 얹는 방향 수",
  "     target_bin_points   8         평활 창 안 목표 점 수",
  "     fine/coarse       4 / 16      분해능 편향 진단용 두 척도",
  "",
  "pipe split outlier_frac  0.08      병합 영역 재분할 발동",
  "     plane_threshold_m   0.015 m",
  "     sigma_u_px          0.2 px    불확실도 산정",
  "     target_sigma_mm     2.0 mm    평활도 목표 정밀도",
]));

body.push(H2("5.5 PDF 사양과의 불일치"));
body.push(P("작업 중 확인된 사항으로, 확인이 필요하다."));
body.push(Gap(60));
body.push(Tbl(
  ["항목", "PDF 사양", "코드값", "함의"],
  [
    ["초점거리", "렌즈 12mm + 3.45µm → f_px ≈ 3478", { t: "1593 (= 5.50mm 렌즈)", c: C.warn },
     "1.2m 시야폭 845mm vs 1844mm"],
    ["DOE 발산각", "투사범위 936×936mm @1.2m → 42.61°", { t: "60.82°", c: C.warn },
     "투사폭 936mm vs 1409mm"],
    ["격자 선 수", "수직20 + 수평20 = 400교점", { t: "21 + 21 = 441교점", c: C.warn },
     "코드 주석은 \"20칸→21선\" 논리"],
  ],
  [1400, 2900, 2400, 2938]));
body.push(Note("f_px=1593은 PDF 5.1 검증표에도 그대로 있어 시뮬레이션 검증용으로 맞춘 값으로 보인다. 실제 하드웨어(12mm 렌즈)로 가면 f가 약 2.2배 커지고, σ_Z = σ_u·Z²/(f·b)에서 깊이 오차가 절반 이하로 개선된다. PDF 5.2에서 「목표 σ_Z ≤ 2mm 미달」이라 한 결론이 렌즈 선정만으로 달라질 수 있으므로 확인할 가치가 있다."));

/* ================= 6. 입력 시험 ================= */
body.push(new Paragraph({ children: [new PageBreak()] }));
body.push(H1("6. 현장 이미지 입력 시험"));

body.push(H2("6.1 시험 방법"));
body.push(P("현장 촬영 이미지(주황 격자, 471×372, 벽+바닥+기둥, 어두운 배경)의 성질을 그대로 재현한 입력을 만들어 A_선검출.detect()를 실제로 실행하였다. 비교군으로 동일 장면에 녹색 격자를 넣은 경우와, 레이저를 통째로 지운 경우를 함께 측정하였다."));

body.push(H2("6.2 결과"));
body.push(Tbl(
  ["입력", "반환 선 수", "화면 안", "실제 격자선까지 평균 거리"],
  [
    ["주황 격자", "21 / 21", "5", { t: "332.05 px", c: C.warn }],
    ["녹색 격자", "21 / 21", "5", { t: "332.03 px", c: C.warn }],
    ["레이저 없음 (장면만)", "21 / 21", "5", { t: "332.05 px", c: C.warn }],
  ],
  [3000, 2200, 1800, 2638]));
body.push(P("로그는 「[A] 완료(최종 통합): V=21/21 H=21/21」로 42개 선 전부 검출 성공으로 표시된다.", { before: 140 }));
body.push(Note("결정적 검증: 레이저를 통째로 지운 이미지와 주황 격자 이미지의 출력이 픽셀 단위로 완전히 동일(0.00px 차이)하다. 즉 출력이 입력 레이저와 아무 상관이 없으며, 검출값이 아니라 기하 예측값이 그대로 반환된 것이다."));

body.push(H2("6.3 원인"));
body.push(H3("① 레이저 색 — 주황은 신호로 잡히지 않음"));
body.push(P("A_선검출의 신호 분리는 G − (R+B)/2이며 녹색 레이저(설계 사양 520nm) 전용이다. 주황·빨강은 음수가 되어 0으로 잘린다. 실제로 주황 이미지에서 이 값의 최대치는 18.0이었는데, 그것은 레이저가 아니라 모래빛 바닥(196,176,120)의 색 편향이었다. 검출기가 바닥을 레이저로 오인하고 추적한 것이다."));
body.push(H3("② f_px 와 해상도 불일치"));
body.push(P("f_px=1593은 2448px 센서 기준값이다. 471px 이미지에 그대로 쓰면 예측 격자가 u = −699 ~ 1170px에 놓여 21개 중 5개만 화면 안에 들어온다. 해상도에 맞춰 환산하면(1593 × 471/2448 = 306.5) 21개 전부 화면 안에 들어오고 평균 오차가 332px에서 7px로 떨어진다. 다만 7px도 격자 간격 23px의 30%라 측정에는 쓸 수 없다."));
body.push(H3("③ 조용한 실패"));
body.push(P("신호가 없으면 _fallback_geom()이 기하 예측을 반환하고, _validate_and_fix()가 이상선을 인접선 보간값으로 교체한다. 그 결과 검출이 0개여도 출력은 항상 42개다. 실패가 성공처럼 보이고, 조작된 좌표가 그대로 삼각측량에 들어가 그럴듯한 각도가 산출된다. 현장에서 가장 위험한 동작이다."));

body.push(H2("6.4 필요 조치"));
body.push(Bul("원본 해상도 이미지 — 리사이즈된 사진은 f_px가 같은 비율로 줄어야 하고, 서브픽셀 정밀도(σ_u≈0.2px)가 원본 기준이라 축소분만큼 손실된다."));
body.push(Bul("레이저 색에 맞는 신호 분리 — 주황이면 R − (G+B)/2, 또는 색과 무관한 ON/OFF 차영상(PDF 2.2에 이미 하드웨어 사양으로 존재)."));
body.push(Bul("해당 장비의 캘리브레이션 값 — 4.2절의 f, b, c_x·c_y, α_i, β_j."));
body.push(Bul("IMU 중력벡터 — 없으면 수직·수평도 자체가 정의되지 않는다."));
body.push(Bul("검출 실패를 거부로 처리 — detect()가 실제 검출률을 반환하고, 임계 미만이면 기하 예측을 채우는 대신 거부하도록 변경."));

/* ================= 7. 검증 ================= */
body.push(new Paragraph({ children: [new PageBreak()] }));
body.push(H1("7. 검증 결과"));

body.push(H2("7.1 회귀 검증 (tests/test_regression.py — 8군 전체 통과)"));
body.push(Tbl(
  ["검증 항목", "결과"],
  [
    ["eq1 삼각측량 복원오차 (0.5 / 1.0 / 1.5 / 2.0 m)", "0.000000 mm"],
    ["eq3 v1 규약 하위호환 (수직도 / 수평도)", "오차 < 1e-6 °"],
    ["eq3 장비 37° 기울임 불변성", "오차 < 1e-6 °"],
    ["중력 두 경로 일치 (IMU vs 카메라 자세, pitch 0/22/90°)", "오차 0"],
    ["eq2 TLS 평면적합 — 경사면", "0.0013° (기존 방식 8.45°)"],
    ["eq2 TLS 평면적합 — 정면 벽 회귀 여부", "0.0000° 차이 (회귀 없음)"],
    ["eq2 축 적합 (0 / 0.6 / 1.2 / 3.0°)", "오차 < 0.03 °"],
    ["eq5 경계 정제 (깊이 불연속 · 마스크 침식)", "정상"],
  ],
  [6800, 2838]));

body.push(H2("7.2 합성 씬 정답 대조"));
body.push(P("벽 + 바닥 + 동바리가 한 프레임에 들어오는 합성 씬(장비 22° 하향, 격자점 4,956개, σ_u=0.2px)에서 두 세그멘테이션 백엔드 모두 전 항목 통과하였다."));
body.push(Gap(60));
body.push(Tbl(
  ["부재", "검측 항목", "정답", "gt 백엔드 오차", "geom 백엔드 오차"],
  [
    ["벽", "수직도", "0.50 °", "0.0016 °", "0.0012 °"],
    ["바닥", "수평도", "0.30 °", "0.0161 °", "0.0049 °"],
    ["동바리", "축 수직도", "1.20 °", "0.0499 °", "0.0443 °"],
    ["벽", "평활도(자 처짐)", "융기 6.0 mm", "5.21 mm (상한 6.54)", "3.85 mm (상한 4.97)"],
  ],
  [1200, 2100, 1800, 2300, 2238]));
body.push(P("허용 기준은 ±0.5°이다.", { before: 100, size: 18, color: C.ink2 }));

body.push(H2("7.3 세그멘테이션 오차 분해"));
body.push(P("Isaac Semantics가 화소별 정답 마스크를 제공하므로, 세그멘테이션 오차만 0으로 만든 상태를 실제로 구성할 수 있다. 이를 기준선으로 두고 마스크를 훼손해가며 최종 오차 중 세그멘테이션이 더하는 몫을 분리 측정하였다."));
body.push(Gap(60));
body.push(Tbl(
  ["조건", "벽", "바닥", "동바리", "판정"],
  [
    ["정답 마스크 (기준선)", "0.0016", "0.0161", "0.0499", "통과"],
    ["마스크 −8px 침식", "0.0013", "0.0072", "0.0043", "통과"],
    ["마스크 +8px 팽창", "0.0014", "0.0170", "0.0443", "통과"],
    ["마스크 +16px 팽창", "0.0014", "0.0287", "0.0443", "통과"],
    ["라벨 오분류 100% (9종 전부)", "복구", "복구", "복구", "통과"],
    ["기하 전용 백엔드 (geom)", "0.0012", "0.0049", "0.0443", "통과"],
    ["σ_u = 2.0 px", "0.0327", "1.3502", "0.0704", { t: "실패", c: C.warn }],
  ],
  [3400, 1500, 1500, 1500, 1738]));
body.push(P("단위는 도(°)이며 허용 기준은 ±0.5°이다.", { before: 100, size: 18, color: C.ink2 }));
body.push(P("각도가 강건한 이유는 네 겹의 방어 때문이다.", { before: 140 }));
body.push(Bul("평면·축 적합이 수천 점을 평균하므로 경계 몇 px는 묻힌다."));
body.push(Bul("의미×기하 융합이 벽/바닥 혼동을 기하로 되돌린다."));
body.push(Bul("병합된 영역을 기하 부정합 검사로 되쪼갠다."));
body.push(Bul("얇은 부재는 robust 축 적합으로 실루엣 오염을 걷어낸다."));
body.push(P("세그멘테이션은 「무엇을 재야 하는지」를 정하고, 「얼마인지」는 기하가 결정하기 때문이다. 다만 다음 둘은 세그멘테이션 품질이 그대로 결과가 된다.", { before: 140 }));
body.push(Bul("부재 종류 구분 — 동바리/기둥/철근, 벽/거푸집/조적은 기하가 구분하지 못한다. 틀리면 각도는 맞아도 KCS 허용치를 잘못 적용한다."));
body.push(Bul("평활도 — 영역 경계와 점 밀도에 직접 좌우된다. σ_u가 0.5px를 넘으면 법선방향 불확실도가 목표 2mm를 넘어 판정이 보류된다."));

/* ================= 8. 한계 ================= */
body.push(H1("8. 한계 및 후속 과제"));

body.push(H2("8.1 확인된 한계"));
body.push(Tbl(
  ["항목", "내용"],
  [
    ["평활도 과소보고", "요철 깊이가 15~40% 낮게 나온다. 노이즈 탓이 아니라 V선 21개의 샘플링 간격이 약 8cm라 σ=5cm 요철이 저샘플링되는 물리적 한계다. 선 수를 늘리거나 촬영을 겹쳐야 개선된다."],
    ["Isaac 렌더 경로 미검증", "어노테이터 부착, 카메라 하향 자세, 선검출 실제 연동은 Isaac 환경이 없어 실행 검증하지 못했다. 계산 로직은 전부 Isaac 비의존 모듈에 있어 오프라인 검증되었다."],
    ["캘리브레이션 미확보", "4.2절 표의 α_i, β_j, R, t, R_ic, b_a가 전부 가정값이다. PDF 3.1이 「B의 정확도가 곧 측정 정확도」라 명시한 부분이 비어 있다."],
    ["세그멘테이션 백엔드", "sam(GroundingDINO+SAM2)·vlm 백엔드는 인터페이스만 있고 미구현이다. GPU와 모델 가중치가 필요해 검증 환경을 확보하지 못했다."],
  ],
  [2400, 7238]));

body.push(H2("8.2 후속 과제"));
body.push(Bul("발사각 α_i 실측 캘리브레이션 — 평면 타깃을 알려진 거리 2점에 두고 각 선의 발사각을 역산하는 절차 및 코드."));
body.push(Bul("선검출 실패의 명시적 거부 — detect()가 검출률을 반환하고 임계 미만이면 기하 예측 대체 없이 거부."));
body.push(Bul("색 무관 신호 분리 및 해상도 자동 환산 — camera_params의 resolution과 입력 이미지 크기가 다르면 f, c_x, c_y를 자동 스케일."));
body.push(Bul("Phase 3 — SAM2 + GroundingDINO 백엔드 구현 및 VLM 라벨링."));
body.push(Bul("Isaac 환경에서 씬 생성 → 촬영 → 영역별 검측 전 구간 실행 검증."));
body.push(Bul("하드웨어 프로토타입 제작 후 실제 콘크리트 환경 현장 검증."));

/* ================= 문서 ================= */
const doc = new Document({
  creator: "광운대학교 건설시스템공학 연구실",
  title: "레이저 그리드 기반 영역별 품질검측 파이프라인",
  description: "구조 · 파라미터 · 입력 데이터 정리",
  styles: {
    default: {
      document: { run: { font: FONT, size: 20, color: C.ink } },
    },
  },
  numbering: {
    config: [{
      reference: "bul",
      levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 480, hanging: 240 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 960, hanging: 240 } } } },
      ],
    }],
  },
  sections: [{
    properties: {
      page: {
        margin: { top: 1134, right: 1134, bottom: 1134, left: 1134 },
      },
    },
    children: body,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("레이저그리드_영역별품질검측_파이프라인_정리.docx", buf);
  console.log("written:", buf.length, "bytes");
});
