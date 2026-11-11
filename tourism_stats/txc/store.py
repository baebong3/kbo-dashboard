"""수집 결과 저장소(공통 스키마)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

METRIC_COLS = ["level", "source", "biz_no", "firm_name", "name_key", "industry", "region",
               "year", "metric", "value", "unit", "detail"]
STATUS_COLS = ["source", "biz_no", "firm_name", "name_key", "industry", "region",
               "status", "status_date", "detail"]


@dataclass
class SourceInfo:
    source: str
    org: str
    kind: str          # API / 파일
    level: str         # firm / industry / status
    reference: str     # URL 또는 파일경로
    rows: int = 0
    years: str = ""
    collected_at: str = field(default_factory=lambda: dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    remark: str = ""


class Store:
    def __init__(self) -> None:
        self._metrics: list[dict] = []
        self._status: list[dict] = []
        self.sources: list[SourceInfo] = []
        self.log: list[dict] = []

    def add_metrics(self, rows: list[dict]) -> None:
        self._metrics.extend(rows)

    def add_status(self, rows: list[dict]) -> None:
        self._status.extend(rows)

    def add_source(self, info: SourceInfo) -> None:
        self.sources.append(info)

    def info(self, source: str, msg: str) -> None:
        self._log("정보", source, msg)

    def warn(self, source: str, msg: str) -> None:
        self._log("경고", source, msg)

    def error(self, source: str, msg: str) -> None:
        self._log("오류", source, msg)

    def _log(self, level: str, source: str, msg: str) -> None:
        self.log.append({"시각": dt.datetime.now().strftime("%H:%M:%S"), "구분": level,
                         "출처": source, "내용": msg})
        print(f"[{level}] {source}: {msg}")

    @property
    def metrics(self) -> pd.DataFrame:
        df = pd.DataFrame(self._metrics, columns=METRIC_COLS)
        for c in ("biz_no", "firm_name", "name_key", "industry", "region", "unit", "detail"):
            df[c] = df[c].fillna("").astype(str)
        if not df.empty:
            df["year"] = df["year"].astype(int)
            df["value"] = df["value"].astype(float)
        return df

    @property
    def status(self) -> pd.DataFrame:
        df = pd.DataFrame(self._status, columns=STATUS_COLS)
        return df.fillna("").astype(str)
