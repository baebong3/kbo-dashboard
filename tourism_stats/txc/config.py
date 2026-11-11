"""설정 로딩 · 조회연도 검증 (최소 3년 ~ 최대 5년)."""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MIN_YEARS = 3
MAX_YEARS = 5


class YearRangeError(ValueError):
    pass


def resolve_years(start: int | None, end: int | None, today: dt.date | None = None) -> list[int]:
    """조회연도 목록을 돌려준다. 3~5개 연도만 허용.

    - 둘 다 없으면: 작년을 끝으로 최근 5년
    - end만 있으면: end 포함 5년
    - start만 있으면: start부터 5년(작년을 넘지 않게, 최소 3년)
    """
    today = today or dt.date.today()
    last_year = today.year - 1
    if start is None and end is None:
        end = last_year
        start = end - (MAX_YEARS - 1)
    elif start is None:
        start = end - (MAX_YEARS - 1)
    elif end is None:
        end = min(start + MAX_YEARS - 1, last_year)
    n = end - start + 1
    if n < MIN_YEARS or n > MAX_YEARS:
        raise YearRangeError(
            f"조회기간은 최소 {MIN_YEARS}년, 최대 {MAX_YEARS}년입니다. "
            f"요청: {start}~{end} ({n}년)"
        )
    if end > today.year:
        raise YearRangeError(f"종료연도({end})가 올해({today.year})보다 큽니다.")
    return list(range(start, end + 1))


def load_dotenv(path: Path) -> None:
    """python-dotenv 없이 .env 읽기(이미 설정된 환경변수는 유지)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v and k not in os.environ:
            os.environ[k] = v


@dataclass
class Config:
    raw: dict[str, Any]
    base_dir: Path
    years: list[int] = field(default_factory=list)

    @property
    def tolerance(self) -> float:
        return float(self.raw.get("validation", {}).get("relative_tolerance", 0.05))

    @property
    def abs_tolerance(self) -> float:
        return float(self.raw.get("validation", {}).get("absolute_tolerance", 0))

    @property
    def source_priority(self) -> list[str]:
        return list(self.raw.get("validation", {}).get("source_priority", []))

    @property
    def industry_aliases(self) -> dict[str, list[str]]:
        return self.raw.get("industry_aliases", {}) or {}

    @property
    def metric_aliases(self) -> dict[str, list[str]]:
        return self.raw.get("metric_aliases", {}) or {}

    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {}) or {}

    def path(self, p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else (self.base_dir / q)

    def api_key(self, section: str) -> str | None:
        env = self.section(section).get("api_key_env")
        return os.environ.get(env) if env else None


def load_config(path: str | Path, start: int | None = None, end: int | None = None) -> Config:
    path = Path(path).resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base = path.parent
    load_dotenv(base / ".env")
    ycfg = raw.get("years", {}) or {}
    years = resolve_years(start if start is not None else ycfg.get("start"),
                          end if end is not None else ycfg.get("end"))
    return Config(raw=raw, base_dir=base, years=years)
