"""使用真实缓存验证解释卡片，不改写股票金融事实。"""

import csv
from pathlib import Path
import unittest

from src.explainer import build_result_cards
from src.screener import screen_stocks


class ResultCardTests(unittest.TestCase):
    def test_real_data_and_missing_record(self):
        path = Path(__file__).resolve().parents[1] / "data" / "stock_dataset.csv"
        if not path.exists():
            self.skipTest("需要真实股票缓存。")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            stocks = list(csv.DictReader(handle))
        results = screen_stocks(stocks, {"growth_improvement": True, "pe_max": 30, "max_drawdown_max": 0.15})
        for stock, result in zip(stocks, results):
            cards = build_result_cards(result)
            self.assertEqual(len(cards), 3)
            self.assertEqual([card["passed"] for card in cards], [reason["passed"] for reason in result["reasons"]])
            for field, card in zip(("revenue_yoy", "pe_ttm", "max_drawdown"), cards):
                if stock[field]:
                    value = float(stock[field])
                    expected = f"{value:.2%}" if field == "max_drawdown" else f"{value:.2f}" + ("%" if field == "revenue_yoy" else "")
                    self.assertEqual(card["value"], expected)
            if stock["revenue_yoy"] and float(stock["revenue_yoy"]) < 0:
                self.assertIn("同比下降", cards[0]["explanation"])
        # 模型或其他上游自由文本不作为事实；缺少记录时不猜测。
        result = results[0]
        for reason in result["reasons"]:
            reason["message"] = "不可信文本"
        self.assertNotIn("不可信文本", str(build_result_cards(result)))
        result["reasons"] = []
        self.assertTrue(all(card["status"] == "待核对" for card in build_result_cards(result)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
