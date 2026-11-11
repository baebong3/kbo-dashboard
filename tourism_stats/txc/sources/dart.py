"""Open DART(금융감독원, 무료) - 기업개황(사업자번호)과 재무제표 주요계정(매출액·영업이익·당기순이익).

연결 순서
  1) corpCode.xml(전체 공시대상 회사 고유번호) 내려받기 → 업체명으로 후보 찾기
  2) company.json(기업개황)의 사업자번호(bizr_no)로 확인
     - 우리 자료에 사업자번호가 있으면: 번호가 같은 후보만 채택
     - 사업자번호가 없으면(인허가 자료 등): 후보가 1개일 때만 채택하고, DART 사업자번호를 채워 넣음
       → 이후 국세청 휴폐업 조회까지 이어짐
  3) fnlttSinglAcnt.json(단일회사 주요계정, 사업보고서) 연도별 조회

주의: 재무 수치 API는 사업보고서 제출 법인(상장사·주요 비상장사)만 제공한다.
      감사보고서만 내는 비상장 외감법인은 기업개황(사업자번호)만 확인되고 재무는 비어 있다.
하루 호출 한도 20,000건(인증키당). 한도 초과(020)면 그 자리에서 멈추고 받은 것까지 저장한다.
"""
from __future__ import annotations

import io
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import requests

from ..config import Config
from ..normalize import norm_bizno, norm_name, to_number
from ..store import SourceInfo, Store

BASE = "https://opendart.fss.or.kr/api"
ACCOUNTS = {"매출액": ["매출액", "수익(매출액)", "영업수익", "매출"],
            "영업이익": ["영업이익", "영업이익(손실)"],
            "당기순이익": ["당기순이익", "당기순이익(손실)"]}
REPRT_ANNUAL = "11011"  # 사업보고서


class DartLimit(RuntimeError):
    pass


class Dart:
    def __init__(self, key: str, pause: float = 0.1):
        self.key, self.pause, self.calls = key, pause, 0

    def get(self, path: str, **params) -> dict:
        self.calls += 1
        time.sleep(self.pause)
        r = requests.get(f"{BASE}/{path}", params={"crtfc_key": self.key, **params}, timeout=30)
        r.raise_for_status()
        d = r.json()
        st = str(d.get("status", "000"))
        if st == "020":
            raise DartLimit("일일 호출 한도 초과(020) - 내일 다시 실행하세요")
        if st in ("010", "011", "012", "901"):
            raise RuntimeError(f"DART 인증키 오류({st}): {d.get('message')}")
        return d if st == "000" else {}

    def corp_codes(self, cache: Path, max_age_days: int = 7) -> dict[str, list[str]]:
        fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < max_age_days * 86400
        if fresh:
            raw = cache.read_bytes()
        else:
            r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": self.key}, timeout=120)
            r.raise_for_status()
            try:
                raw = zipfile.ZipFile(io.BytesIO(r.content)).read("CORPCODE.xml")
            except zipfile.BadZipFile as e:
                raise RuntimeError(f"corpCode.xml 응답이 zip이 아님(인증키 확인): {r.text[:200]}") from e
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(raw)
        out: dict[str, list[str]] = {}
        for el in ET.fromstring(raw).iter("list"):
            out.setdefault(norm_name(el.findtext("corp_name")), []).append(el.findtext("corp_code"))
        return out


def match_corp(api: Dart, biz: str | None, cands: list[str]) -> tuple[str | None, dict, str]:
    """(corp_code, 기업개황, 매칭방법)"""
    if not cands:
        return None, {}, ""
    if biz:
        for c in cands:
            info = api.get("company.json", corp_code=c)
            if norm_bizno(info.get("bizr_no")) == biz:
                return c, info, "사업자번호 일치"
        return None, {}, ""
    if len(cands) == 1:
        info = api.get("company.json", corp_code=cands[0])
        if info:
            return cands[0], info, "업체명 유일 일치(사업자번호는 DART 값)"
    return None, {}, ""


def load_dart(cfg: Config, store: Store, firms: list[tuple[str | None, str]]) -> None:
    """firms: [(사업자번호 또는 '', 업체명)]"""
    sec = cfg.section("dart")
    if not sec.get("enabled", False):
        return
    key = cfg.api_key("dart")
    if not key:
        store.warn("DART", f"인증키 없음(환경변수 {sec.get('api_key_env')}) → 건너뜀")
        return
    api = Dart(key, float(sec.get("pause_sec", 0.1)))
    try:
        codes = api.corp_codes(cfg.path(sec.get("cache", "output/cache/CORPCODE.xml")))
    except Exception as e:  # noqa: BLE001
        store.error("DART", f"고유번호 목록 실패: {e}")
        return

    seen, metric_rows, firm_rows = set(), [], []
    n_fin = 0
    try:
        for biz, name in firms[: int(sec.get("max_firms", 500))]:
            nk = norm_name(name)
            if not nk or (biz or nk) in seen:
                continue
            seen.add(biz or nk)
            corp, info, how = match_corp(api, biz or None, codes.get(nk, []))
            if not corp:
                continue
            dart_biz = norm_bizno(info.get("bizr_no")) or biz
            detail = f"corp_code {corp}, {how}, 법인구분 {info.get('corp_cls', '')}"
            firm_rows.append({"source": "DART 기업개황", "biz_no": dart_biz or "", "firm_name": name,
                              "name_key": nk, "industry": "", "region": "", "status": "",
                              "status_date": "", "detail": detail})
            got = False
            for y in cfg.years:
                fs = api.get("fnlttSinglAcnt.json", corp_code=corp, bsns_year=str(y), reprt_code=REPRT_ANNUAL)
                lst = fs.get("list", [])
                items = [i for i in lst if i.get("fs_div") == sec.get("fs_div", "OFS")] or lst
                for metric, names in ACCOUNTS.items():
                    hit = next((i for i in items if i.get("account_nm") in names), None)
                    v = to_number(hit.get("thstrm_amount")) if hit else None
                    if v is None:
                        continue
                    got = True
                    metric_rows.append({"level": "firm", "source": "DART", "biz_no": dart_biz or "",
                                        "firm_name": name, "name_key": nk, "industry": "", "region": "",
                                        "year": y, "metric": metric, "value": v / 1e6, "unit": "백만원",
                                        "detail": f"{detail}, {hit.get('fs_nm', '')}"})
            n_fin += got
    except DartLimit as e:
        store.warn("DART", str(e))
    except RuntimeError as e:
        store.error("DART", str(e))

    store.add_metrics(metric_rows)
    store.add_status(firm_rows)  # 상태값은 비우고 사업자번호·고유번호 연결용으로만 사용
    store.add_source(SourceInfo(source="DART", org="금융감독원 전자공시", kind="API", level="firm",
                                reference="https://opendart.fss.or.kr", rows=len(metric_rows),
                                years=f"{cfg.years[0]}~{cfg.years[-1]}",
                                remark=f"연결 {len(firm_rows)}개사(재무 있음 {n_fin}개사), 호출 {api.calls}건"))
    store.info("DART", f"연결 {len(firm_rows)}개사, 재무 {n_fin}개사, 지표 {len(metric_rows)}건, 호출 {api.calls}건")
