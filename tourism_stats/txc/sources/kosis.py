"""KOSIS 공유서비스(Open API) - 관광산업조사(구 관광사업체조사) 등 업종별 통계.

- 통계표 검색: statisticsSearch.do  → `python -m txc discover`
- 자료 조회 : Param/statisticsParameterData.do (연도별로 나눠 호출, 셀 4만 개 제한 회피)
"""
from __future__ import annotations

import time

import requests

from ..config import Config
from ..normalize import build_alias_lookup, canon, metric_kind, norm_region, to_number, unit_factor
from ..store import SourceInfo, Store

SEARCH_URL = "https://kosis.kr/openapi/statisticsSearch.do"
DATA_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"


class KosisError(RuntimeError):
    pass


def _get(url: str, params: dict, timeout: int = 30, retries: int = 3) -> list[dict]:
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("err"):
                # err 30: 데이터 없음
                if str(data.get("err")) == "30":
                    return []
                raise KosisError(f"KOSIS 오류 {data.get('err')}: {data.get('errMsg')}")
            return data if isinstance(data, list) else []
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(2 ** i)
    raise KosisError(f"KOSIS 호출 실패: {last}")


def search_tables(api_key: str, keyword: str, count: int = 100) -> list[dict]:
    params = {"method": "getList", "apiKey": api_key, "searchNm": keyword, "orgId": "",
              "sort": "RANK", "startCount": 1, "resultCount": count, "format": "json", "jsonVD": "Y"}
    return _get(SEARCH_URL, params)


def fetch_table(api_key: str, org_id: str, tbl_id: str, year: int, obj_levels: int = 2,
                itm_id: str = "ALL", obj_values: dict | None = None) -> list[dict]:
    params = {"method": "getList", "apiKey": api_key, "orgId": org_id, "tblId": tbl_id,
              "itmId": itm_id, "prdSe": "Y", "startPrdDe": str(year), "endPrdDe": str(year),
              "format": "json", "jsonVD": "Y"}
    obj_values = obj_values or {}
    for i in range(1, obj_levels + 1):
        params[f"objL{i}"] = obj_values.get(f"objL{i}", "ALL")
    return _get(DATA_URL, params)


def _pick_metric(itm_nm: str, metric_map: dict[str, str], lookup: dict[str, str]) -> str | None:
    if metric_map:
        for pat, metric in metric_map.items():
            if pat in itm_nm:
                return metric
        return None
    return canon(itm_nm, lookup)


def load_kosis(cfg: Config, store: Store) -> None:
    sec = cfg.section("kosis")
    if not sec.get("enabled", False):
        return
    key = cfg.api_key("kosis")
    if not key:
        store.warn("KOSIS", f"인증키 없음(환경변수 {sec.get('api_key_env')}) → 건너뜀")
        return
    ind_lookup = build_alias_lookup(cfg.industry_aliases)
    met_lookup = build_alias_lookup(cfg.metric_aliases)
    for t in sec.get("tables", []) or []:
        if not t.get("enabled", True):
            continue
        name = t.get("name") or t["tbl_id"]
        src = f"KOSIS:{name}"
        rows, raw_n, tbl_nm = [], 0, ""
        for y in cfg.years:
            try:
                data = fetch_table(key, str(t.get("org_id", "113")), t["tbl_id"], y,
                                   int(t.get("obj_levels", 2)), t.get("itm_id", "ALL"),
                                   t.get("obj_values"))
            except KosisError as e:
                store.error(src, f"{y}년 조회 실패: {e}")
                continue
            if not data:
                store.warn(src, f"{y}년 자료 없음(미공표 가능)")
            raw_n += len(data)
            for d in data:
                tbl_nm = d.get("TBL_NM", tbl_nm)
                metric = _pick_metric(d.get("ITM_NM", ""), t.get("metric_map") or {}, met_lookup)
                val = to_number(d.get("DT"))
                if not metric or val is None:
                    continue
                try:
                    f, u = unit_factor(metric_kind(metric), d.get("UNIT_NM"))
                except ValueError:
                    store.warn(src, f"단위 해석 불가: {d.get('UNIT_NM')} ({metric})")
                    continue
                ind_dim, reg_dim = t.get("industry_dim", "C1_NM"), t.get("region_dim")
                industry = canon(d.get(ind_dim, ""), ind_lookup) if ind_dim else t.get("industry", "")
                region = norm_region(d.get(reg_dim)) if reg_dim else "전국"
                rows.append({"level": "industry", "source": src, "biz_no": None, "firm_name": "",
                             "name_key": "", "industry": industry, "region": region,
                             "year": int(str(d.get("PRD_DE"))[:4]), "metric": metric,
                             "value": val * f, "unit": u,
                             "detail": f"{t['tbl_id']} {d.get('ITM_NM', '')}"})
        store.add_metrics(rows)
        store.add_source(SourceInfo(
            source=src, org=t.get("org", "문화체육관광부·한국문화관광연구원"), kind="API", level="industry",
            reference=f"https://kosis.kr/statHtml/statHtml.do?orgId={t.get('org_id', '113')}&tblId={t['tbl_id']}",
            rows=len(rows), years=f"{cfg.years[0]}~{cfg.years[-1]}", remark=tbl_nm))
        store.info(src, f"원자료 {raw_n}셀 → 표준 {len(rows)}건")
