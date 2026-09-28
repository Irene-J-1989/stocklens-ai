"""真实 API 数据的确定性筛选测试；不构造股票或行情。

运行：.\\.venv\\Scripts\\python.exe -X utf8 tests/test_screener.py
边界测试只改变策略阈值，保留真实股票数据不变。
"""

from datetime import datetime, time, timedelta
import json
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fuyao_client import FuyaoClient, SHANGHAI_TZ
from src.metrics import calculate_max_drawdown
from src.screener import screen_stocks


class ScreenerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        client = FuyaoClient()
        code = "600519.SH"
        if code not in {item["thscode"] for item in client.get_hs300_components()}:
            raise AssertionError("测试股票不在 API 返回的沪深300股票池中。")
        valuations = client.get_valuation_snapshot(code)
        if len(valuations) != 1:
            raise AssertionError("缺少测试股票的真实估值数据。")
        financial = client.get_financial_indicators(code, "2026-2")
        now = datetime.now(SHANGHAI_TZ)
        end = now.date() if now.time() >= time(15) else now.date() - timedelta(days=1)
        for days in (120, 240, 365):
            bars = client.get_historical_prices(code, end - timedelta(days=days), end)
            if len(bars) >= 60:
                break
        if len(bars) < 60:
            raise AssertionError("真实行情不足60根，无法构造筛选输入。")
        cls.stock = {
            "code": valuations[0]["thscode"], "name": valuations[0]["name"],
            "revenue_growth_yoy": financial["calculate_operating_income_yoy_growth_ratio"],
            "pe_ttm": valuations[0]["pe_ttm"],
            "max_drawdown": calculate_max_drawdown([bar["close_price"] for bar in bars[-60:]]),
        }
        cls.conditions = {"growth_improvement": True, "pe_max": 30, "max_drawdown_max": 0.15}

    def test_real_stock_decisions(self) -> None:
        result = screen_stocks([self.stock], self.conditions)[0]
        growth = self.stock["revenue_growth_yoy"]
        pe = self.stock["pe_ttm"]
        expected = [growth is not None and float(growth) > 0,
                    pe is not None and pe < 30, self.stock["max_drawdown"] < 0.15]
        self.assertEqual(set(result), {"code", "name", "selected", "reasons", "failed_conditions"})
        self.assertEqual(result["code"], self.stock["code"])
        self.assertEqual(result["name"], self.stock["name"])
        self.assertEqual([reason["passed"] for reason in result["reasons"]], expected)
        self.assertEqual(result["selected"], all(expected))
        self.assertEqual(result["failed_conditions"], [key for key, passed in zip(self.conditions, expected) if not passed])
        print("真实数据：报告期 2026-2；最大回撤基于最近60根前复权日K线。")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    def test_strict_thresholds_and_disabled_growth(self) -> None:
        # 阈值设为实际观测值，验证严格小于以及失败后仍判断其他条件。
        conditions = {**self.conditions, "growth_improvement": False,
                      "max_drawdown_max": self.stock["max_drawdown"]}
        pe = self.stock["pe_ttm"]
        if pe is not None and pe > 0:
            conditions["pe_max"] = pe
        result = screen_stocks([self.stock], conditions)[0]
        self.assertFalse(result["selected"])
        self.assertEqual(len(result["reasons"]), 3)
        self.assertIsNone(result["reasons"][0]["passed"])
        self.assertNotIn("growth_improvement", result["failed_conditions"])
        self.assertIn("max_drawdown_max", result["failed_conditions"])
        if pe is not None and pe > 0:
            self.assertIn("pe_max", result["failed_conditions"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
