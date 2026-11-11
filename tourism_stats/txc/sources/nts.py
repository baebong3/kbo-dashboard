"""국세청 사업자등록 상태조회(공공데이터포털 odcloud) - 계속/휴업/폐업 여부, 폐업일."""
from __future__ import annotations

import time
from urllib.parse import unquote

import requests

from ..config import Config
from ..normalize import norm_date, norm_status
from ..store import SourceInfo, Store

STATUS_URL = "https://api.odcloud.kr/api/nts-businessman/v1/status"
BATCH = 100  # API 1회 최대 100건


def query_status(api_key: str, biz_nos: list[str], timeout: int = 30) -> list[dict]:
    key = unquote(api_key)  # Encoding 키를 넣어도 이중 인코딩되지 않게
    out: list[dict] = []
    for i in range(0, len(biz_nos), BATCH):
        chunk = biz_nos[i:i + BATCH]
        for attempt in range(3):
            try:
                r = requests.post(STATUS_URL, params={"serviceKey": key, "returnType": "JSON"},
                                  json={"b_no": chunk}, timeout=timeout)
                r.raise_for_status()
                out.extend(r.json().get("data", []))
                break
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
    return out


def load_nts(cfg: Config, store: Store, biz_nos: list[str]) -> None:
    sec = cfg.section("nts")
    if not sec.get("enabled", False):
        return
    key = cfg.api_key("nts")
    if not key:
        store.warn("국세청", f"인증키 없음(환경변수 {sec.get('api_key_env')}) → 건너뜀")
        return
    biz_nos = sorted({b for b in biz_nos if b})
    if not biz_nos:
        store.warn("국세청", "조회할 사업자번호가 없습니다.")
        return
    try:
        data = query_status(key, biz_nos)
    except Exception as e:  # noqa: BLE001
        store.error("국세청", f"상태조회 실패: {e}")
        return
    rows = []
    for d in data:
        st = norm_status(d.get("b_stt_cd") or d.get("b_stt") or d.get("tax_type"))
        if not st and "등록되지 않은" in str(d.get("tax_type", "")):
            st = "미등록"
        rows.append({"source": "국세청 휴폐업조회", "biz_no": d.get("b_no"), "firm_name": "",
                     "name_key": "", "industry": "", "region": "", "status": st,
                     "status_date": norm_date(d.get("end_dt")),
                     "detail": " / ".join(x for x in [d.get("tax_type", ""),
                                                      f"과세유형전환 {norm_date(d.get('tax_type_change_dt'))}"
                                                      if d.get("tax_type_change_dt") else ""] if x)})
    store.add_status(rows)
    store.add_source(SourceInfo(source="국세청 휴폐업조회", org="국세청(공공데이터포털)", kind="API",
                                level="status", reference=STATUS_URL, rows=len(rows), years="조회일 기준",
                                remark="계속사업자/휴업자/폐업자, 폐업일"))
    store.info("국세청", f"{len(biz_nos)}개 사업자번호 조회 → {len(rows)}건")
