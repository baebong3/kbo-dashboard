"""Open DART(선택) - 외부감사·공시 대상 관광업체의 재무제표 매출액·영업이익.

업체명으로 고유번호(corp_code)를 찾고, 기업개황의 사업자번호(bizr_no)가 일치할 때만 채택한다.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import requests

from ..config import Config
from ..normalize import norm_bizno, norm_name, to_number
from ..store import SourceInfo, Store

BASE = "https://opendart.fss.or.kr/api"
ACCOUNTS = {"매출액": ["매출액", "수익(매출액)", "영업수익", "매출"], "영업이익": ["영업이익", "영업이익(손실)"],
            "당기순이익": ["당기순이익", "당기순이익(손실)"]}


def _corp_codes(key: str, cache: Path) -> dict[str, list[str]]:
    if cache.exists():
        raw = cache.read_bytes()
    else:
        r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
        r.raise_for_status()
        raw = zipfile.ZipFile(io.BytesIO(r.content)).read("CORPCODE.xml")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(raw)
    out: dict[str, list[str]] = {}
    for el in ET.fromstring(raw).iter("list"):
        out.setdefault(norm_name(el.findtext("corp_name")), []).append(el.findtext("corp_code"))
    return out


def load_dart(cfg: Config, store: Store, firms: list[tuple[str | None, str]]) -> None:
    """firms: [(사업자번호, 업체명)]"""
    sec = cfg.section("dart")
    if not sec.get("enabled", False):
        return
    key = cfg.api_key("dart")
    if not key:
        store.warn("DART", f"인증키 없음(환경변수 {sec.get('api_key_env')}) → 건너뜀")
        return
    try:
        codes = _corp_codes(key, cfg.path(sec.get("cache", "output/cache/CORPCODE.xml")))
    except Exception as e:  # noqa: BLE001
        store.error("DART", f"고유번호 목록 실패: {e}")
        return
    rows, matched = [], 0
    for biz, name in firms[: int(sec.get("max_firms", 300))]:
        cands = codes.get(norm_name(name), [])
        corp = None
        for c in cands:
            try:
                info = requests.get(f"{BASE}/company.json", params={"crtfc_key": key, "corp_code": c},
                                    timeout=30).json()
            except Exception:  # noqa: BLE001
                continue
            if biz and norm_bizno(info.get("bizr_no")) == biz:
                corp = c
                break
        if not corp:
            continue
        matched += 1
        for y in cfg.years:
            try:
                fs = requests.get(f"{BASE}/fnlttSinglAcnt.json", params={
                    "crtfc_key": key, "corp_code": corp, "bsns_year": str(y), "reprt_code": "11011"},
                    timeout=30).json()
            except Exception:  # noqa: BLE001
                continue
            items = [i for i in fs.get("list", []) if i.get("fs_div") == sec.get("fs_div", "OFS")] or fs.get("list", [])
            for metric, names in ACCOUNTS.items():
                hit = next((i for i in items if i.get("account_nm") in names), None)
                v = to_number(hit.get("thstrm_amount")) if hit else None
                if v is None:
                    continue
                rows.append({"level": "firm", "source": "DART", "biz_no": biz, "firm_name": name,
                             "name_key": norm_name(name), "industry": "", "region": "", "year": y,
                             "metric": metric, "value": v / 1e6, "unit": "백만원",
                             "detail": f"corp_code {corp} {hit.get('fs_nm', '')}"})
    store.add_metrics(rows)
    store.add_source(SourceInfo(source="DART", org="금융감독원", kind="API", level="firm",
                                reference=BASE, rows=len(rows), years=f"{cfg.years[0]}~{cfg.years[-1]}",
                                remark=f"사업자번호 일치 {matched}개사"))
    store.info("DART", f"{matched}개사 매칭, {len(rows)}건")
