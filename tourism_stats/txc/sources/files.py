"""파일 기반 출처 적재기.

NICE비즈라인 엑셀 내려받기, 관광산업조사 업체별 원자료, 호텔업 운영현황, 유원시설업(테마파크업) 현황,
지방행정 인허가(LOCALDATA) CSV 등 형식이 제각각인 파일을 설정(config.yaml)의 열 대응표로 읽는다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import Config
from ..normalize import (build_alias_lookup, canon, metric_kind, norm_bizno, norm_date, norm_name,
                         norm_region, norm_status, to_number, unit_factor)
from ..store import SourceInfo, Store

STD_FIELDS = {"biz_no", "firm_name", "industry", "region", "year", "status", "status_date",
              "open_date", "address", "metric", "value", "unit", "detail"}
DEFAULT_WIDE = r"^(?P<metric>.+?)[\s_(\[]*(?P<year>(19|20)\d{2})(년)?[)\]]*$"


def read_table(path: Path, sheet: Any = 0, header_row: int = 1) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet, header=header_row - 1, dtype=str)
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, header=header_row - 1, dtype=str, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 알 수 없습니다: {path}")


def load_file_sources(cfg: Config, store: Store) -> None:
    for spec in cfg.raw.get("files", []) or []:
        if not spec.get("enabled", True):
            continue
        name = spec["name"]
        if cfg.raw.get("official_only", False) and not spec.get("official", True):
            store.info(name, "공식자료 아님(official: false) → official_only 설정으로 제외")
            continue
        path = cfg.path(spec["path"])
        if not path.exists():
            store.warn(name, f"파일 없음 → 건너뜀: {path}")
            continue
        try:
            _load_one(cfg, store, spec, path)
        except Exception as e:  # noqa: BLE001
            store.error(name, f"적재 실패: {e}")


def _load_one(cfg: Config, store: Store, spec: dict, path: Path) -> None:
    name = spec["name"]
    level = spec.get("level", "firm")
    df = read_table(path, spec.get("sheet", 0), int(spec.get("header_row", 1)))
    df.columns = [str(c).strip() for c in df.columns]
    colmap: dict[str, str] = spec.get("columns", {}) or {}
    missing = [c for c in colmap if c not in df.columns]
    if missing:
        store.warn(name, f"설정에 있으나 파일에 없는 열: {missing}")
    df = df.rename(columns={k: v for k, v in colmap.items() if k in df.columns})
    for k, v in (spec.get("fixed", {}) or {}).items():
        df[k] = v

    ind_lookup = build_alias_lookup(cfg.industry_aliases)
    met_lookup = build_alias_lookup(cfg.metric_aliases)
    units: dict[str, str] = spec.get("units", {}) or {}
    default_unit = spec.get("default_unit")
    years = set(cfg.years)

    metric_cols = [v for k, v in colmap.items() if v not in STD_FIELDS and v in df.columns]
    fmt = spec.get("format", "long")
    long_rows: list[dict] = []

    def base(r: pd.Series) -> dict:
        return {
            "biz_no": norm_bizno(r.get("biz_no")),
            "firm_name": (str(r.get("firm_name")).strip() if pd.notna(r.get("firm_name")) else ""),
            "industry": canon(r.get("industry"), ind_lookup),
            "region": norm_region(r.get("region") if pd.notna(r.get("region", None)) else r.get("address")),
        }

    if fmt == "wide":
        pat = re.compile(spec.get("wide_pattern", DEFAULT_WIDE))
        wide_cols = []
        for c in df.columns:
            m = pat.match(c)
            if m and c not in STD_FIELDS:
                wide_cols.append((c, m.group("metric").strip(), int(m.group("year"))))
        if not wide_cols:
            raise ValueError("wide 형식인데 '지표_연도' 형태의 열을 찾지 못했습니다.")
        for _, r in df.iterrows():
            b = base(r)
            for c, met, yr in wide_cols:
                long_rows.append({**b, "year": yr, "metric": canon(met, met_lookup), "value": r[c],
                                  "unit": units.get(met, default_unit)})
    elif "metric" in df.columns and "value" in df.columns:
        for _, r in df.iterrows():
            met = canon(r["metric"], met_lookup)
            long_rows.append({**base(r), "year": r.get("year"), "metric": met, "value": r["value"],
                              "unit": r.get("unit") if pd.notna(r.get("unit", None)) else units.get(met, default_unit)})
    elif metric_cols:
        if "year" not in df.columns:
            raise ValueError("연도 열(year)이 없습니다. columns 또는 fixed에 year를 지정하세요.")
        for _, r in df.iterrows():
            b = base(r)
            for mc in metric_cols:
                src_col = next(k for k, v in colmap.items() if v == mc)
                long_rows.append({**b, "year": r["year"], "metric": canon(mc, met_lookup), "value": r[mc],
                                  "unit": units.get(mc, units.get(src_col, default_unit))})

    out, skipped_unit = [], 0
    for row in long_rows:
        yr = _year(row["year"])
        val = to_number(row["value"])
        if yr is None or yr not in years or val is None:
            continue
        try:
            f, u = unit_factor(metric_kind(row["metric"]), row.get("unit"))
        except ValueError:
            skipped_unit += 1
            continue
        out.append({
            "level": "firm" if level in ("firm", "status") else "industry",
            "source": name, "biz_no": row["biz_no"] if level != "industry" else None,
            "firm_name": row["firm_name"] if level != "industry" else "",
            "name_key": norm_name(row["firm_name"]) if level != "industry" else "",
            "industry": row["industry"], "region": row["region"],
            "year": yr, "metric": row["metric"], "value": val * f, "unit": u, "detail": str(path.name),
        })
    if skipped_unit:
        store.warn(name, f"단위 해석 불가로 {skipped_unit}건 제외")
    store.add_metrics(out)

    n_status = 0
    if level == "status" or "status" in df.columns:
        st_rows = []
        for _, r in df.iterrows():
            b = base(r)
            if not b["biz_no"] and not b["firm_name"]:
                continue
            st_rows.append({"source": name, **b, "name_key": norm_name(b["firm_name"]),
                            "status": norm_status(r.get("status")),
                            "status_date": norm_date(r.get("status_date")),
                            "detail": norm_date(r.get("open_date")) and f"인허가일 {norm_date(r.get('open_date'))}"})
        store.add_status(st_rows)
        n_status = len(st_rows)
        if spec.get("derive_counts") and "open_date" in df.columns:
            store.add_metrics(_derive_counts(df, name, cfg, ind_lookup))

    yrs = sorted({r["year"] for r in out})
    store.add_source(SourceInfo(
        source=name, org=spec.get("org", ""), kind="파일", level=level, reference=str(path),
        rows=len(out) + n_status, years=f"{yrs[0]}~{yrs[-1]}" if yrs else "-",
        remark=spec.get("remark", "")))
    store.info(name, f"지표 {len(out)}건, 상태 {n_status}건 적재")


def _derive_counts(df: pd.DataFrame, name: str, cfg: Config, ind_lookup: dict) -> list[dict]:
    """인허가일·폐업일로 연말 기준 영업 사업체 수를 산출(업종×시도, 전국)."""
    d = pd.DataFrame({
        "industry": df.get("industry", pd.Series([""] * len(df))).map(lambda v: canon(v, ind_lookup)),
        "region": (df["region"] if "region" in df.columns else df.get("address", pd.Series([None] * len(df)))).map(norm_region),
        "open": df["open_date"].map(norm_date),
        "close": df.get("status_date", pd.Series([None] * len(df))).map(norm_date),
        "status": df.get("status", pd.Series([None] * len(df))).map(norm_status),
    })
    rows = []
    for y in cfg.years:
        eoy = f"{y}-12-31"
        alive = d[(d["open"] != "") & (d["open"] <= eoy) &
                  ~((d["status"] == "폐업") & (d["close"] != "") & (d["close"] <= eoy))]
        regional = [(k, g) for k, g in alive.groupby(["industry", "region"]) if k[1] != "전국"]
        national = [((i, "전국"), g) for i, g in alive.groupby("industry")]
        for (ind, reg), g in regional + national:
            rows.append({"level": "industry", "source": f"{name}(인허가 산출)", "biz_no": None, "firm_name": "",
                         "name_key": "", "industry": ind, "region": reg, "year": y, "metric": "사업체수",
                         "value": float(len(g)), "unit": "개", "detail": "인허가일≤연말, 폐업일>연말"})
    return rows


def _year(v: Any) -> int | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    m = re.search(r"(19|20)\d{2}", str(v))
    return int(m.group(0)) if m else None
