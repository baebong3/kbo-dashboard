"""표준화: 사업자번호, 업체명, 단위, 업종명, 지표명, 영업상태."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

# 금액은 모두 '백만원'으로 환산
MONEY_TO_MILLION = {
    "원": 1e-6,
    "천원": 1e-3,
    "만원": 1e-2,
    "백만원": 1.0,
    "십억원": 1e3,
    "억원": 1e2,
    "조원": 1e6,
}
COUNT_UNITS = {"개", "개소", "업체", "사업체", "명", "실", "객실", "개실", "건", "개사", "곳"}

_CORP_TOKENS = [
    r"\(주\)", r"㈜", r"주식회사", r"\(유\)", r"유한회사", r"유한책임회사", r"\(재\)", r"재단법인",
    r"\(사\)", r"사단법인", r"\(합\)", r"합자회사", r"합명회사", r"co\.?,?\s*ltd\.?", r"inc\.?", r"corp\.?",
]
_CORP_RE = re.compile("|".join(_CORP_TOKENS), re.IGNORECASE)


def norm_bizno(v: Any) -> str | None:
    """사업자등록번호 10자리 문자열(숫자만). 형식 오류면 None."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    d = re.sub(r"\D", "", s)
    if len(d) == 9:  # 엑셀에서 앞자리 0이 빠진 경우
        d = "0" + d
    return d if len(d) == 10 else None


def bizno_checksum_ok(b: str) -> bool:
    """국세청 사업자번호 검증식."""
    if not b or len(b) != 10 or not b.isdigit():
        return False
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(int(b[i]) * w[i] for i in range(9))
    s += (int(b[8]) * 5) // 10
    return (10 - s % 10) % 10 == int(b[9])


def fmt_bizno(b: str | None) -> str:
    return f"{b[:3]}-{b[3:5]}-{b[5:]}" if b and len(b) == 10 else ""


def norm_name(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = _CORP_RE.sub("", str(v))
    s = re.sub(r"[\s\-·.,'\"()\[\]]", "", s)
    return s.lower()


def to_number(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if pd.isna(v) else float(v)
    s = str(v).strip().replace(",", "")
    if s in {"", "-", "x", "X", "…", "...", "NA", "nan", "None"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


def unit_factor(metric_kind: str, unit: str | None) -> tuple[float, str]:
    """(곱할 계수, 표준단위)."""
    u = (unit or "").strip().replace(" ", "")
    if metric_kind == "money":
        if u in MONEY_TO_MILLION:
            return MONEY_TO_MILLION[u], "백만원"
        if u == "":
            return 1.0, "백만원"
        raise ValueError(f"알 수 없는 금액 단위: {unit}")
    if metric_kind == "count":
        return 1.0, (u or "")
    return 1.0, u


MONEY_METRICS = {"매출액", "영업이익", "당기순이익", "부가가치", "인건비", "영업비용", "자산총계", "객실매출", "입장수입"}


def metric_kind(metric: str) -> str:
    return "money" if metric in MONEY_METRICS or metric.endswith("액") or "매출" in metric else "count"


def build_alias_lookup(aliases: dict[str, list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for canon, alts in aliases.items():
        out[_key(canon)] = canon
        for a in alts or []:
            out[_key(a)] = canon
    return out


def _key(s: str) -> str:
    return re.sub(r"[\s·()\[\]_\-]", "", str(s)).lower()


def canon(v: Any, lookup: dict[str, str]) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return lookup.get(_key(s), s)


STATUS_MAP = {
    "01": "영업", "계속사업자": "영업", "영업": "영업", "영업/정상": "영업", "정상": "영업", "운영": "영업", "운영중": "영업",
    "02": "휴업", "휴업자": "휴업", "휴업": "휴업", "휴업중": "휴업",
    "03": "폐업", "폐업자": "폐업", "폐업": "폐업", "취소/말소/만료/정지/중지": "폐업", "말소": "폐업", "취소": "폐업",
}


def norm_status(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s in STATUS_MAP:
        return STATUS_MAP[s]
    for k, val in STATUS_MAP.items():
        if len(k) > 2 and k in s:
            return val
    if "등록되지 않은" in s:
        return "미등록"
    return s


def norm_date(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    d = re.sub(r"\D", "", str(v))
    if len(d) >= 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return ""


SIDO = {
    "서울": ["서울특별시", "서울시", "서울"], "부산": ["부산광역시", "부산"], "대구": ["대구광역시", "대구"],
    "인천": ["인천광역시", "인천"], "광주": ["광주광역시", "광주"], "대전": ["대전광역시", "대전"],
    "울산": ["울산광역시", "울산"], "세종": ["세종특별자치시", "세종"], "경기": ["경기도", "경기"],
    "강원": ["강원특별자치도", "강원도", "강원"], "충북": ["충청북도", "충북"], "충남": ["충청남도", "충남"],
    "전북": ["전북특별자치도", "전라북도", "전북"], "전남": ["전라남도", "전남"], "경북": ["경상북도", "경북"],
    "경남": ["경상남도", "경남"], "제주": ["제주특별자치도", "제주도", "제주"],
}
_SIDO_LOOKUP = {a: k for k, alts in SIDO.items() for a in alts}
NATIONAL = {"전국", "계", "합계", "총계", "전체", "소계"}


def norm_region(v: Any) -> str:
    """시도 약칭. 주소가 들어와도 첫 단어로 판정. 빈값/전국/계 → '전국'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "전국"
    s = str(v).strip()
    if not s or s in NATIONAL:
        return "전국"
    first = s.split()[0]
    return _SIDO_LOOKUP.get(first, _SIDO_LOOKUP.get(s, s))
