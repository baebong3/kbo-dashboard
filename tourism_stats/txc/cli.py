"""명령행 진입점.

  python -m txc run      --config config.yaml [--start 2020 --end 2024]
  python -m txc discover --config config.yaml [--keyword 관광산업조사]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

from .config import YearRangeError, load_config
from .report import write_csv, write_excel
from .sources.dart import load_dart
from .sources.files import load_file_sources
from .sources.kosis import KosisError, load_kosis, search_tables
from .sources.nts import load_nts
from .store import Store
from .validate import run_validation


def cmd_run(a: argparse.Namespace) -> int:
    cfg = load_config(a.config, a.start, a.end)
    print(f"조회기간: {cfg.years[0]}~{cfg.years[-1]} ({len(cfg.years)}개년)")
    store = Store()
    load_kosis(cfg, store)
    load_file_sources(cfg, store)
    m, st = store.metrics, store.status
    firms = pd.concat([m.loc[m["level"] == "firm", ["biz_no", "firm_name"]], st[["biz_no", "firm_name"]]])
    load_nts(cfg, store, [b for b in firms["biz_no"] if b])
    pairs = (firms[(firms["biz_no"] != "") & (firms["firm_name"] != "")]
             .drop_duplicates("biz_no")[["biz_no", "firm_name"]].itertuples(index=False, name=None))
    load_dart(cfg, store, list(pairs))

    res = run_validation(cfg, store)
    out_dir = cfg.path(cfg.raw.get("output_dir", "output"))
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    xlsx = write_excel(cfg, store, res, out_dir / f"관광산업_상호검증_{cfg.years[0]}-{cfg.years[-1]}_{stamp}.xlsx")
    print(f"\n엑셀 결과: {xlsx}")
    if a.csv:
        for p in write_csv(res, out_dir / f"csv_{stamp}"):
            print(f"CSV: {p}")
    bad = len(res.mismatches)
    print(f"불일치 {bad}건 → '불일치목록' 시트 확인")
    return 0


def cmd_discover(a: argparse.Namespace) -> int:
    cfg = load_config(a.config)
    key = cfg.api_key("kosis")
    if not key:
        print("KOSIS 인증키가 없습니다(.env의 KOSIS_API_KEY).", file=sys.stderr)
        return 2
    kws = a.keyword or cfg.section("kosis").get("search_keywords", ["관광산업조사"])
    rows = []
    for kw in kws:
        try:
            for d in search_tables(key, kw):
                rows.append({"검색어": kw, "기관ID": d.get("ORG_ID"), "기관": d.get("ORG_NM"),
                             "통계표ID": d.get("TBL_ID"), "통계표명": d.get("TBL_NM"),
                             "조사명": d.get("STAT_NM") or d.get("STAT_ID"),
                             "수록기간": f"{d.get('STRT_PRD_DE', '')}~{d.get('END_PRD_DE', '')}",
                             "URL": d.get("LINK_URL") or d.get("TBL_VIEW_URL", "")})
        except KosisError as e:
            print(f"[오류] {kw}: {e}", file=sys.stderr)
    df = pd.DataFrame(rows).drop_duplicates(subset=["통계표ID"]) if rows else pd.DataFrame()
    out = cfg.path(cfg.raw.get("output_dir", "output")) / "KOSIS_통계표_검색결과.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out, index=False)
    with pd.option_context("display.max_rows", 200, "display.width", 200):
        print(df[["기관ID", "통계표ID", "통계표명", "수록기간"]] if not df.empty else "결과 없음")
    print(f"\n저장: {out}\n→ 필요한 통계표ID를 config.yaml의 kosis.tables에 넣으세요.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="txc", description="관광산업 통계 통합·상호검증")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="수집 → 상호검증 → 엑셀 결과")
    r.add_argument("--config", default="config.yaml")
    r.add_argument("--start", type=int, help="시작연도(최소 3년, 최대 5년)")
    r.add_argument("--end", type=int, help="종료연도")
    r.add_argument("--csv", action="store_true", help="SPSS·R용 CSV도 저장")
    r.set_defaults(func=cmd_run)
    d = sub.add_parser("discover", help="KOSIS 통계표ID 검색")
    d.add_argument("--config", default="config.yaml")
    d.add_argument("--keyword", action="append")
    d.set_defaults(func=cmd_discover)
    a = p.parse_args(argv)
    try:
        return a.func(a)
    except YearRangeError as e:
        print(f"[조회기간 오류] {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
