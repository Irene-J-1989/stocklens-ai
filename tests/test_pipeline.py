"""全量真实 API 集成测试，以及隔离的故障注入测试（不伪造金融数值）。

运行：.\\.venv\\Scripts\\python.exe -X utf8 tests/test_pipeline.py
全量获取沪深300，可能需要数分钟；默认缓存会更新。
"""

import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_pipeline import COLUMNS, DEFAULT_DATASET, build_stock_dataset
from src.fuyao_client import FuyaoAPIError, FuyaoClient
from src.screener import screen_stocks


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = FuyaoClient()
        cls.components = cls.client.get_hs300_components()
        cls.frame = build_stock_dataset(report="2026-2", client=cls.client)

    def test_stock_count_and_schema(self) -> None:
        self.assertEqual(len(self.frame), len(self.components))
        self.assertEqual(set(self.frame["code"]), {item["thscode"] for item in self.components})
        self.assertEqual(list(self.frame.columns), COLUMNS)
        self.assertTrue(self.frame["code"].is_unique)
        self.assertFalse(self.frame[["code", "name"]].isna().any().any())
        self.assertTrue(self.frame[COLUMNS[2:]].notna().any().all(), "全部指标缺失，不能视为真实集成成功。")
        self.assertTrue(self.frame["max_drawdown"].dropna().between(0, 1).all())
        print(f"股票数量：{len(self.frame)}")
        print(f"字段：{list(self.frame.columns)}")
        print(f"缺失数量：{self.frame.isna().sum().to_dict()}")

    def test_cache_and_screener(self) -> None:
        cached = pd.read_csv(DEFAULT_DATASET, encoding="utf-8-sig", dtype={"code": str, "name": str})
        pd.testing.assert_frame_equal(cached, self.frame, check_dtype=False)
        metadata = json.loads(DEFAULT_DATASET.with_suffix(".meta.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["stock_count"], len(self.frame))
        self.assertEqual(metadata["errors"], self.frame.attrs["errors"])
        for error in metadata["errors"]:
            value = self.frame.loc[self.frame["code"] == error["code"], error["stage"]]
            self.assertTrue(value.isna().all())
        results = screen_stocks(cached.to_dict("records"), {
            "growth_improvement": True, "pe_max": 30, "max_drawdown_max": 0.15})
        self.assertEqual(len(results), len(cached))
        for row, result in zip(cached.to_dict("records"), results):
            self.assertEqual(result["reasons"][0]["field"], "revenue_yoy")
            if any(pd.isna(row[field]) for field in COLUMNS[2:]):
                self.assertFalse(result["selected"])

    def test_failures_preserve_missing_values(self) -> None:
        # 股票身份来自真实股票池；仅注入异常，绝不返回模拟财务/行情数值。
        component = self.components[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stock_dataset.csv"
            with patch.object(self.client, "get_hs300_components", return_value=[component]), \
                 patch.object(self.client, "get_valuation_snapshot", side_effect=FuyaoAPIError("测试注入：估值请求失败")), \
                 patch.object(self.client, "get_financial_indicators", side_effect=FuyaoAPIError("测试注入：财务请求失败")), \
                 patch.object(self.client, "get_historical_prices", side_effect=FuyaoAPIError("测试注入：K线请求失败")):
                failed = build_stock_dataset(report="2026-2", cache_path=path, client=self.client)
            self.assertEqual(len(failed), 1)
            self.assertTrue(failed[COLUMNS[2:]].isna().all().all())
            self.assertEqual(len(failed.attrs["errors"]), 3)
            cached = pd.read_csv(path)
            self.assertTrue(cached[COLUMNS[2:]].isna().all().all())
            previous = path.read_bytes()
            with patch.object(self.client, "get_hs300_components", side_effect=FuyaoAPIError("测试注入：股票池失败")):
                with self.assertRaises(FuyaoAPIError):
                    build_stock_dataset(cache_path=path, client=self.client)
            self.assertEqual(path.read_bytes(), previous)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    unittest.main(verbosity=2)
