"""python -m unittest discover -s tests  (인터넷 불필요: API는 가짜 응답으로 검사)"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from txc.config import YearRangeError, load_config, resolve_years  # noqa: E402
from txc.normalize import (bizno_checksum_ok, norm_bizno, norm_name, norm_region,  # noqa: E402
                           norm_status, unit_factor)
from txc.sources import kosis, nts  # noqa: E402
from txc.store import Store  # noqa: E402
from txc.validate import compare_group, run_validation  # noqa: E402
from txc.sources.files import load_file_sources  # noqa: E402


class TestYears(unittest.TestCase):
    today = dt.date(2026, 11, 11)

    def test_default_5y(self):
        self.assertEqual(resolve_years(None, None, self.today), [2021, 2022, 2023, 2024, 2025])

    def test_min_max(self):
        self.assertEqual(len(resolve_years(2022, 2024, self.today)), 3)
        with self.assertRaises(YearRangeError):
            resolve_years(2023, 2024, self.today)
        with self.assertRaises(YearRangeError):
            resolve_years(2018, 2024, self.today)

    def test_start_only(self):
        self.assertEqual(resolve_years(2023, None, self.today), [2023, 2024, 2025])
        with self.assertRaises(YearRangeError):
            resolve_years(2024, None, self.today)


class TestNormalize(unittest.TestCase):
    def test_bizno(self):
        self.assertEqual(norm_bizno("083-01-66135"), "0830166135")
        self.assertEqual(norm_bizno(830166135), "0830166135")
        self.assertIsNone(norm_bizno("12-34"))
        self.assertTrue(bizno_checksum_ok("5260181593"))
        self.assertFalse(bizno_checksum_ok("5260181594"))

    def test_name_region_status(self):
        self.assertEqual(norm_name("(주)가람 관광호텔"), norm_name("가람관광호텔 주식회사"))
        self.assertEqual(norm_region("강원도 춘천시"), "강원")
        self.assertEqual(norm_region("계"), "전국")
        self.assertEqual(norm_status("폐업자"), "폐업")
        self.assertEqual(norm_status("영업/정상"), "영업")

    def test_units(self):
        self.assertEqual(unit_factor("money", "천원"), (1e-3, "백만원"))
        self.assertEqual(unit_factor("money", "억원"), (100.0, "백만원"))
        with self.assertRaises(ValueError):
            unit_factor("money", "달러")


class TestCompare(unittest.TestCase):
    def test_verdicts(self):
        v, c, note, _ = compare_group({"A": 100, "B": 103}, "백만원", 0.05, 0, ["A"])
        self.assertEqual((v, c), ("일치", 100))
        v, c, note, rel = compare_group({"A": 100, "B": 120}, "백만원", 0.05, 0, ["A"])
        self.assertEqual(v, "불일치")
        self.assertIn("B 120백만원(+20.0%)", note)
        v, *_ = compare_group({"A": 100}, "", 0.05, 0, [])
        self.assertEqual(v, "단일출처")
        v, c, *_ = compare_group({"KOSIS:표1": 50, "X": 50}, "", 0.05, 0, ["KOSIS"])
        self.assertEqual(c, 50)


class FakeResp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class TestApis(unittest.TestCase):
    def test_kosis_parse(self):
        data = [{"TBL_NM": "업종별 현황", "PRD_DE": "2023", "C1_NM": "관광호텔", "ITM_NM": "매출액",
                 "UNIT_NM": "백만원", "DT": "1,234"},
                {"TBL_NM": "업종별 현황", "PRD_DE": "2023", "C1_NM": "관광호텔", "ITM_NM": "사업체수",
                 "UNIT_NM": "개", "DT": "10"}]
        cfg = load_config(ROOT / "config.sample.yaml", 2021, 2023)
        cfg.raw["kosis"] = {"enabled": True, "api_key_env": "TXC_TEST_KEY",
                            "tables": [{"name": "t", "org_id": "113", "tbl_id": "DT_T", "industry_dim": "C1_NM"}]}
        os.environ["TXC_TEST_KEY"] = "x"
        store = Store()
        with mock.patch.object(kosis.requests, "get", side_effect=lambda *a, **k: FakeResp(
                data if k["params"]["startPrdDe"] == "2023" else {"err": "30", "errMsg": "데이터가 없습니다"})):
            kosis.load_kosis(cfg, store)
        m = store.metrics
        self.assertEqual(len(m), 2)
        self.assertEqual(set(m["industry"]), {"관광호텔업"})   # 별칭 변환
        self.assertEqual(m.loc[m.metric == "매출액", "value"].iloc[0], 1234.0)

    def test_nts_batches(self):
        calls = []

        def fake_post(url, params, json, timeout):
            calls.append(len(json["b_no"]))
            return FakeResp({"data": [{"b_no": b, "b_stt": "폐업자", "b_stt_cd": "03", "end_dt": "20230630",
                                       "tax_type": "부가가치세 일반과세자"} for b in json["b_no"]]})
        with mock.patch.object(nts.requests, "post", side_effect=fake_post):
            out = nts.query_status("k%2Bey", [f"{i:010d}" for i in range(250)])
        self.assertEqual(calls, [100, 100, 50])
        self.assertEqual(len(out), 250)


class TestEndToEnd(unittest.TestCase):
    def test_sample(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(ROOT / "sample_data", tmp / "sample_data")
            shutil.copy(ROOT / "config.sample.yaml", tmp / "config.yaml")
            cfg = load_config(tmp / "config.yaml")
            store = Store()
            load_file_sources(cfg, store)
            res = run_validation(cfg, store)
            mm = res.mismatches
            # 솔숲테마파크 2023·2024 매출 불일치(NICE vs 관광산업조사)
            self.assertEqual(len(mm[(mm["구분"] == "업체별") & mm["대상"].str.contains("솔숲")]), 2)
            # 바다마루호텔: 사업자번호 없는 호텔업 자료와 업체명으로 연결되어 2024 매출 불일치
            self.assertTrue(((mm["구분"] == "업체별") & mm["대상"].str.contains("바다마루") & (mm["연도"] == 2024)).any())
            # 한빛호텔: 국세청 폐업 후 실적 존재
            st = mm[mm["구분"] == "영업상태"]
            self.assertTrue(st["비고"].str.contains("폐업\\(2023-06-30\\) 이후").any())
            # 솔숲: 인허가 휴업 vs 국세청 영업
            self.assertTrue(st["비고"].str.contains("휴업").any())
            # 테마파크업 → 종합유원시설업 별칭, 억원 → 백만원
            iw = res.industry_wide
            row = iw[(iw["업종"] == "종합유원시설업") & (iw["연도"] == 2022) & (iw["지표"] == "매출액")]
            self.assertEqual(row["테마파크업 현황"].iloc[0], 48000)
            self.assertEqual(len(res.firms), 6)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
