"""엑셀 결과서 + SPSS/R용 CSV 출력."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .config import Config
from .store import Store
from .validate import Result

NAVY = "1F3864"
HEAD_FILL = PatternFill("solid", fgColor="D9E1F2")
BAD_FILL = PatternFill("solid", fgColor="FCE4D6")
ONE_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="BFBFBF")
FONT = "맑은 고딕"


def _sheet(wb: Workbook, title: str, df: pd.DataFrame, note: str = "",
           money_cols: tuple[str, ...] = (), pct_cols: tuple[str, ...] = ("최대차이율", "포괄률"),
           wide_text: tuple[str, ...] = ("비고",)) -> None:
    ws = wb.create_sheet(title)
    r0 = 1
    if note:
        ws.cell(1, 1, note).font = Font(name=FONT, size=9, color="595959")
        r0 = 3
    if df is None or df.empty:
        ws.cell(r0, 1, "해당 자료 없음").font = Font(name=FONT)
        return
    cols = list(df.columns)
    for j, c in enumerate(cols, 1):
        cell = ws.cell(r0, j, c)
        cell.font = Font(name=FONT, bold=True, color=NAVY)
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(top=Side(style="medium", color=NAVY), bottom=THIN)
    verdict_idx = cols.index("판정") + 1 if "판정" in cols else None
    for i, row in enumerate(df.itertuples(index=False), r0 + 1):
        fill = None
        if verdict_idx:
            v = row[verdict_idx - 1]
            fill = BAD_FILL if v == "불일치" else (ONE_FILL if v == "단일출처" else None)
        for j, v in enumerate(row, 1):
            if isinstance(v, float) and pd.isna(v):
                v = None
            cell = ws.cell(i, j, v)
            cell.font = Font(name=FONT, size=10)
            cell.border = Border(bottom=THIN)
            name = cols[j - 1]
            if isinstance(v, (int, float)) and name != "연도":
                cell.number_format = "0.0%" if name in pct_cols else ("#,##0" if abs(v) >= 100 or float(v).is_integer() else "#,##0.0")
            if name in wide_text:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            if fill:
                cell.fill = fill
    for j, c in enumerate(cols, 1):
        width = 60 if c in wide_text else min(max(len(str(c)) * 2 + 2, 10), 28)
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.freeze_panes = ws.cell(r0 + 1, 1)
    ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(cols))}{r0 + len(df)}"


def write_excel(cfg: Config, store: Store, res: Result, out: Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    yrs = f"{cfg.years[0]}~{cfg.years[-1]}년({len(cfg.years)}개년)"

    # 요약
    def cnt(df: pd.DataFrame, v: str) -> int:
        return int((df["판정"] == v).sum()) if not df.empty and "판정" in df else 0

    summary = pd.DataFrame([
        ["조회기간", yrs],
        ["작성일시", dt.datetime.now().strftime("%Y-%m-%d %H:%M")],
        ["허용오차", f"상대 {cfg.tolerance:.0%} 이내 일치 (절대 {cfg.abs_tolerance:g} 이하 차이도 일치)"],
        ["출처 우선순위(채택값 기준)", " > ".join(cfg.source_priority) or "(미지정 - 첫 출처)"],
        ["통합 업체 수", len(res.firms)],
        ["업체별 비교 건수", len(res.firm_wide)],
        ["  ├ 일치", cnt(res.firm_wide, "일치")],
        ["  ├ 불일치", cnt(res.firm_wide, "불일치")],
        ["  └ 단일출처", cnt(res.firm_wide, "단일출처")],
        ["업종별 비교 건수", len(res.industry_wide)],
        ["  ├ 일치", cnt(res.industry_wide, "일치")],
        ["  ├ 불일치", cnt(res.industry_wide, "불일치")],
        ["  └ 단일출처", cnt(res.industry_wide, "단일출처")],
        ["영업상태 불일치 업체", cnt(res.status, "불일치")],
        ["수집 경고·오류", sum(1 for x in store.log if x["구분"] != "정보")],
    ], columns=["항목", "내용"])
    _sheet(wb, "요약", summary, "관광산업 통계 통합·상호검증 결과 - 금액 단위 백만원, 불일치 행은 주황색, 단일출처는 회색")
    _sheet(wb, "불일치목록", res.mismatches, "출처가 여러 개인데 값·상태가 맞지 않는 항목(비고에 출처별 값과 기준 대비 차이율)")
    _sheet(wb, "업체별_통합", res.firm_wide, "업체×연도×지표, 열마다 출처별 값. 채택값은 출처 우선순위 기준")
    _sheet(wb, "업종별_통합", res.industry_wide, "업종×시도×연도×지표. KOSIS 관광산업조사·호텔업·테마파크업 조사·인허가 산출값 비교")
    _sheet(wb, "영업상태", res.status, "국세청 휴폐업조회·인허가 영업상태 비교, 폐업 후 실적·실적 누락 연도 점검")
    _sheet(wb, "포괄률(참고)", res.coverage, "업체자료 합계 ÷ 공식 업종통계. 표본 차이로 불일치 판정에는 넣지 않음")
    _sheet(wb, "업체목록", res.firms, "출처 통합 업체 마스터")
    raw = res.metrics_long.drop(columns=["name_key"], errors="ignore").rename(columns={
        "level": "수준", "source": "출처", "biz_no": "사업자번호", "firm_name": "업체명", "industry": "업종",
        "region": "시도", "year": "연도", "metric": "지표", "value": "값", "unit": "단위", "detail": "세부",
        "firm_key": "업체키", "match": "매칭방법"})
    _sheet(wb, "원자료(long)", raw, "모든 출처의 표준화된 원자료", wide_text=("세부",))
    src = pd.DataFrame([s.__dict__ for s in store.sources]).rename(columns={
        "source": "출처", "org": "작성기관", "kind": "방식", "level": "수준", "reference": "URL·파일",
        "rows": "건수", "years": "연도", "collected_at": "수집일시", "remark": "비고"}) if store.sources else pd.DataFrame()
    _sheet(wb, "출처정보", src)
    _sheet(wb, "수집로그", pd.DataFrame(store.log), wide_text=("내용",))

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def write_csv(res: Result, out_dir: Path) -> list[Path]:
    """SPSS·R에서 바로 읽도록 UTF-8(BOM) CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, df in [("firm_wide", res.firm_wide), ("industry_wide", res.industry_wide),
                     ("status", res.status), ("metrics_long", res.metrics_long)]:
        if df is None or df.empty:
            continue
        p = out_dir / f"{name}.csv"
        df.to_csv(p, index=False, encoding="utf-8-sig")
        paths.append(p)
    return paths
