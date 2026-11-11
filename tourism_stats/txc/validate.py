"""상호검증 엔진.

1) 업체 식별 통합: 사업자번호 우선, 없으면 정규화 업체명(+시도)으로 연결
2) 업체별 지표: 같은 (업체, 연도, 지표)를 출처 간 비교 → 일치/불일치/단일출처, 불일치는 비고에 값·차이 기록
3) 영업상태: 국세청 휴폐업 vs 인허가(LOCALDATA)·업체조사 상태, 폐업 이후 실적 존재 여부
4) 업종별 지표: KOSIS 관광산업조사 vs 호텔업·테마파크업 조사 vs 인허가 산출 사업체수,
   그리고 업체자료 합계 대비 공식통계 포괄률(참고)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config
from .normalize import bizno_checksum_ok, fmt_bizno, norm_name
from .store import Store


@dataclass
class Result:
    firm_wide: pd.DataFrame
    industry_wide: pd.DataFrame
    status: pd.DataFrame
    coverage: pd.DataFrame
    mismatches: pd.DataFrame
    firms: pd.DataFrame
    metrics_long: pd.DataFrame


def _fmt(v: float, unit: str) -> str:
    if v is None or pd.isna(v):
        return "-"
    s = f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:,.1f}"
    return f"{s}{unit}"


# ---------------------------------------------------------------- 업체 식별
def assign_firm_keys(m: pd.DataFrame, st: pd.DataFrame, store: Store) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rec = pd.concat([
        m.loc[m["level"] == "firm", ["biz_no", "firm_name", "name_key", "region", "industry", "source"]],
        st[["biz_no", "firm_name", "name_key", "region", "industry", "source"]],
    ], ignore_index=True)
    # 이름 → 사업자번호 (유일할 때만)
    nb = rec[(rec["biz_no"] != "") & (rec["name_key"] != "")]
    name_to_biz: dict[str, str] = {}
    for nk, g in nb.groupby("name_key"):
        uniq = g["biz_no"].unique()
        if len(uniq) == 1:
            name_to_biz[nk] = uniq[0]
        else:
            store.warn("업체매칭", f"같은 업체명에 사업자번호 {len(uniq)}개: {g['firm_name'].iloc[0]} → 이름 매칭 보류")

    def key(row) -> str:
        if row["biz_no"]:
            return row["biz_no"]
        if row["name_key"] in name_to_biz:
            return name_to_biz[row["name_key"]]
        return f"NM:{row['name_key']}|{row['region'] or ''}" if row["name_key"] else ""

    def match_how(row) -> str:
        if row["biz_no"]:
            return "사업자번호"
        return "업체명" if row["name_key"] in name_to_biz else "업체명(번호없음)"

    for df in (m, st):
        if df.empty:
            df["firm_key"] = []
            df["match"] = []
            continue
        df["firm_key"] = df.apply(key, axis=1)
        df["match"] = df.apply(match_how, axis=1)
    m.loc[m["level"] != "firm", ["firm_key", "match"]] = ""

    # 업체 마스터
    allrec = pd.concat([m[m["level"] == "firm"], st], ignore_index=True)
    allrec = allrec[allrec["firm_key"] != ""]
    rows = []
    for fk, g in allrec.groupby("firm_key"):
        names = [n for n in g["firm_name"].dropna().unique() if n]
        inds = [i for i in g["industry"].dropna().unique() if i]
        regs = [r for r in g["region"].dropna().unique() if r and r != "전국"]
        biz = fk if not fk.startswith("NM:") else ""
        remark = []
        if len({norm_name(n) for n in names}) > 1:
            remark.append("출처별 업체명 상이: " + ", ".join(names[:4]))
        if len(inds) > 1:
            remark.append("출처별 업종 상이: " + ", ".join(inds))
        if len(regs) > 1:
            remark.append("출처별 시도 상이: " + ", ".join(regs))
        if biz and not bizno_checksum_ok(biz):
            remark.append("사업자번호 검증식 불일치(오기 가능)")
        if not biz:
            remark.append("사업자번호 없음 - 업체명으로만 식별")
        rows.append({"업체키": fk, "사업자번호": fmt_bizno(biz), "업체명": names[0] if names else "",
                     "업종": inds[0] if inds else "", "시도": regs[0] if regs else "",
                     "출처": ", ".join(sorted(g["source"].unique())), "출처수": g["source"].nunique(),
                     "비고": "; ".join(remark)})
    firms = pd.DataFrame(rows)
    return m, st, firms


# ---------------------------------------------------------------- 공통 비교
def compare_group(vals: dict[str, float], unit: str, tol: float, abs_tol: float,
                  priority: list[str]) -> tuple[str, float | None, str, float | None]:
    """(판정, 채택값, 비고, 최대차이율)"""
    vals = {k: v for k, v in vals.items() if v is not None and not pd.isna(v)}
    if not vals:
        return "자료없음", None, "", None
    chosen_src = next((p for p in priority if p in vals), None)
    if chosen_src is None:
        # 우선순위 목록에 없는 출처는 접두어로 매칭(KOSIS:* 등)
        chosen_src = next((s for p in priority for s in vals if s.startswith(p)), next(iter(vals)))
    chosen = vals[chosen_src]
    if len(vals) == 1:
        return "단일출처", chosen, f"{chosen_src}만 보유", None
    arr = np.array(list(vals.values()), dtype=float)
    ref = abs(chosen) if chosen else max(abs(arr).max(), 1e-9)
    diffs = {s: (v - chosen) / ref if ref else 0.0 for s, v in vals.items()}
    max_rel = max(abs(d) for d in diffs.values())
    max_abs = arr.max() - arr.min()
    if max_rel <= tol or max_abs <= abs_tol:
        note = "" if max_rel == 0 else f"허용오차 내 차이(최대 {max_rel:.1%})"
        return "일치", chosen, note, max_rel
    parts = [f"{s} {_fmt(v, unit)}" + ("" if s == chosen_src else f"({diffs[s]:+.1%})")
             for s, v in vals.items()]
    return "불일치", chosen, f"출처 간 불일치[기준 {chosen_src}]: " + " / ".join(parts), max_rel


def _wide(df: pd.DataFrame, keys: list[str], cfg: Config) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    sources = sorted(df["source"].unique(), key=lambda s: (_prio(s, cfg.source_priority), s))
    out = []
    for k, g in df.groupby(keys + ["year", "metric"], dropna=False):
        unit = g["unit"].iloc[0]
        dup_notes = []
        vals = {}
        for s, gs in g.groupby("source"):
            if len(gs) > 1 and gs["value"].nunique() > 1:
                dup_notes.append(f"{s} 내부 중복 {len(gs)}건(값 {', '.join(_fmt(v, '') for v in gs['value'].unique()[:3])}) → 합계 아닌 첫 값 사용")
            vals[s] = gs["value"].iloc[0]
        verdict, chosen, note, rel = compare_group(vals, unit, cfg.tolerance, cfg.abs_tolerance, cfg.source_priority)
        row = dict(zip(keys + ["연도", "지표"], k))
        row["단위"] = unit
        for s in sources:
            row[s] = vals.get(s, np.nan)
        row.update({"채택값": chosen, "출처수": len(vals), "최대차이율": rel, "판정": verdict,
                    "비고": "; ".join([n for n in [note] + dup_notes if n])})
        out.append(row)
    return pd.DataFrame(out)


def _prio(s: str, priority: list[str]) -> int:
    for i, p in enumerate(priority):
        if s == p or s.startswith(p):
            return i
    return len(priority)


# ---------------------------------------------------------------- 영업상태
def check_status(st: pd.DataFrame, m: pd.DataFrame, firms: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    if firms.empty:
        return pd.DataFrame()
    fm = m[m["level"] == "firm"]
    rows = []
    for _, f in firms.iterrows():
        fk = f["업체키"]
        g = st[st["firm_key"] == fk]
        row = {"업체키": fk, "사업자번호": f["사업자번호"], "업체명": f["업체명"], "업종": f["업종"]}
        notes = []
        statuses = {}
        for _, r in g.iterrows():
            if not r["status"]:   # DART 기업개황 등 연결용 행
                continue
            statuses[r["source"]] = r["status"]
            row[f"{r['source']}_상태"] = r["status"]
            if r["status_date"]:
                row[f"{r['source']}_폐업(휴업)일"] = r["status_date"]
        uniq = {v for v in statuses.values() if v}
        if len(uniq) > 1:
            notes.append("출처 간 영업상태 불일치: " + " / ".join(f"{s} {v}" for s, v in statuses.items()))
        # 폐업일 이후 실적
        closed = g[(g["status"] == "폐업") & (g["status_date"] != "")]
        if not closed.empty:
            cy = int(closed["status_date"].min()[:4])
            after = fm[(fm["firm_key"] == fk) & (fm["year"] > cy) & (fm["value"] > 0)]
            if not after.empty:
                notes.append(f"폐업({closed['status_date'].min()}) 이후 연도 실적 존재: " +
                             ", ".join(sorted({f"{r.source} {r.year}년 {r.metric}" for r in after.itertuples()})[:5]))
        if "미등록" in uniq:
            notes.append("국세청 미등록 사업자번호(오기 또는 법인 변경 확인 필요)")
        # 조회기간 중 실적 공백
        yrs = set(fm.loc[fm["firm_key"] == fk, "year"].unique())
        opened = [int(d[-10:-6]) for d in g["detail"] if d.startswith("인허가일 ")]
        first = min(opened) if opened else min(years)
        gaps = [y for y in years if y not in yrs and y >= first]
        if yrs and gaps and "폐업" not in uniq:
            notes.append(f"실적 누락 연도: {', '.join(map(str, gaps))}")
        row["판정"] = "불일치" if any(n.startswith(("출처 간", "폐업(", "국세청 미등록")) for n in notes) else (
            "확인" if g.empty is False else "상태자료없음")
        row["비고"] = "; ".join(notes)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 포괄률
def coverage(m: pd.DataFrame, ind_wide: pd.DataFrame) -> pd.DataFrame:
    fm = m[(m["level"] == "firm") & (m["industry"] != "")]
    if fm.empty or ind_wide.empty:
        return pd.DataFrame()
    rows = []
    agg = fm.groupby(["source", "industry", "year", "metric"]).agg(합계=("value", "sum"), 업체수=("firm_key", "nunique")).reset_index()
    for r in agg.itertuples():
        off = ind_wide[(ind_wide["업종"] == r.industry) & (ind_wide["시도"] == "전국") &
                       (ind_wide["연도"] == r.year) & (ind_wide["지표"] == r.metric)]
        if off.empty or pd.isna(off["채택값"].iloc[0]):
            continue
        o = off["채택값"].iloc[0]
        cov = r.합계 / o if o else np.nan
        note = ""
        if cov > 1.05:
            note = "업체자료 합계가 공식통계를 초과 - 업종분류 또는 단위 확인 필요"
        elif cov < 0.3:
            note = "포괄률 30% 미만 - 업체자료 표본이 작음(참고용)"
        rows.append({"업체자료 출처": r.source, "업종": r.industry, "연도": r.year, "지표": r.metric,
                     "업체수": r.업체수, "업체자료 합계": r.합계, "공식통계(채택값)": o,
                     "포괄률": cov, "비고": note})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 실행
def run_validation(cfg: Config, store: Store) -> Result:
    m, st = store.metrics, store.status
    if m.empty and st.empty:
        raise RuntimeError("수집된 자료가 없습니다. 수집로그를 확인하세요.")
    m, st, firms = assign_firm_keys(m, st, store)
    # 업체자료의 업종·시도 결측은 마스터 값으로 보완
    if not firms.empty:
        fmap = firms.set_index("업체키")
        for col, src in (("industry", "업종"), ("region", "시도")):
            mask = (m["level"] == "firm") & ((m[col] == "") | m[col].isna() | (m[col] == "전국"))
            m.loc[mask, col] = m.loc[mask, "firm_key"].map(fmap[src]).fillna(m.loc[mask, col])

    fm = m[m["level"] == "firm"].copy()
    firm_wide = _wide(fm, ["firm_key"], cfg)
    if not firm_wide.empty:
        firm_wide = firms[["업체키", "사업자번호", "업체명", "업종", "시도"]].merge(
            firm_wide.rename(columns={"firm_key": "업체키"}), on="업체키", how="right")
        firm_wide = firm_wide.sort_values(["업종", "업체명", "지표", "연도"]).reset_index(drop=True)

    im = m[m["level"] == "industry"].copy()
    ind_wide = _wide(im, ["industry", "region"], cfg)
    if not ind_wide.empty:
        ind_wide = ind_wide.rename(columns={"industry": "업종", "region": "시도"})
        ind_wide["시도순"] = (ind_wide["시도"] != "전국").astype(int)
        ind_wide = ind_wide.sort_values(["업종", "시도순", "시도", "지표", "연도"]).drop(columns="시도순").reset_index(drop=True)

    status = check_status(st, m, firms, cfg.years)
    cov = coverage(m, ind_wide)

    mm = []
    if not firm_wide.empty:
        x = firm_wide[firm_wide["판정"] == "불일치"]
        mm.append(pd.DataFrame({"구분": "업체별", "대상": x["업체명"] + " (" + x["사업자번호"].fillna("") + ")",
                                "연도": x["연도"], "지표": x["지표"], "최대차이율": x["최대차이율"], "비고": x["비고"]}))
    if not ind_wide.empty:
        x = ind_wide[ind_wide["판정"] == "불일치"]
        mm.append(pd.DataFrame({"구분": "업종별", "대상": x["업종"] + " / " + x["시도"],
                                "연도": x["연도"], "지표": x["지표"], "최대차이율": x["최대차이율"], "비고": x["비고"]}))
    if not status.empty:
        x = status[status["판정"] == "불일치"]
        mm.append(pd.DataFrame({"구분": "영업상태", "대상": x["업체명"] + " (" + x["사업자번호"].fillna("") + ")",
                                "연도": np.nan, "지표": "영업상태", "최대차이율": np.nan, "비고": x["비고"]}))
    mismatches = pd.concat(mm, ignore_index=True) if mm else pd.DataFrame()
    return Result(firm_wide, ind_wide, status, cov, mismatches, firms, m)
