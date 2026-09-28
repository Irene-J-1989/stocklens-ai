"""意图边界测试；解释测试读取已有真实缓存，不调用 API。"""

import csv
import json
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ai_parser import parse_rule_intent as parse_intent, validate_intent
from src.explainer import explain_conditions, explain_results
from src.screener import screen_stocks


class IntentTests(unittest.TestCase):
    def test_normal(self):
        result = parse_intent("帮我选出经营改善、估值合理且走势稳定的股票")
        self.assertEqual(result["conditions"], {"growth_improvement": True, "pe_max": 30, "max_drawdown_max": 0.15})
        self.assertFalse(result["need_clarification"])
        self.assertEqual(set(result["interpretation"]), {"growth_improvement", "valuation", "stability"})
        json.dumps(result, allow_nan=False)

    def test_ambiguous(self):
        for text in ("", "选好股票", "经营改善、估值合理、走势稳定、收益高", "经营改善或估值合理或走势稳定"):
            with self.subTest(text=text):
                result = parse_intent(text)
                self.assertTrue(result["need_clarification"])
                with self.assertRaises(ValueError):
                    explain_results([], result)

    def test_partial_and_disabled_conditions(self):
        cases = [("只要求增长", "收入增长明显", "growth_condition"),
                 ("只要求估值", "估值合理", "pe_condition"),
                 ("只要求稳定", "走势稳定", "stability_condition"),
                 ("明确不关注", "我想找成长性比较好的公司，希望收入增长明显，不太关注短期股价波动。", "growth_condition")]
        for label, text, active in cases:
            with self.subTest(label=label):
                result = parse_intent(text)
                self.assertFalse(result["need_clarification"])
                for state in ("growth_condition", "pe_condition", "stability_condition"):
                    self.assertEqual(result[state]["status"], "enabled" if state == active else "disabled")
        result = parse_intent("不要求经营改善、估值合理、走势稳定")
        self.assertFalse(result["need_clarification"])
        self.assertEqual(result["growth_condition"]["status"], "disabled")

    def test_conflicts(self):
        for text in ("低估值但PE超过50", "PE超过50但估值合理", "经营改善但营收同比下降"):
            with self.subTest(text=text):
                result = parse_intent(text)
                self.assertTrue(result["need_clarification"])
                self.assertTrue(result["conflicts"])
                self.assertIn("需要澄清", explain_conditions(result))

    def test_explicit_bounds(self):
        result = parse_intent("经营改善，PE低于20，最大回撤低于10%")
        self.assertFalse(result["need_clarification"])
        self.assertEqual(result["conditions"]["pe_max"], 20)
        self.assertEqual(result["conditions"]["max_drawdown_max"], 0.1)

    def test_reject_facts(self):
        result = parse_intent("经营改善、估值合理、走势稳定")
        result["conditions"]["stock_name"] = "禁止生成事实"
        with self.assertRaises(ValueError):
            validate_intent(result)

    def test_explanation_from_real_cache(self):
        path = PROJECT_ROOT / "data" / "stock_dataset.csv"
        if not path.exists():
            self.skipTest("尚无真实缓存，请先运行流水线。")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            stocks = list(csv.DictReader(handle))[:2]
        self.assertTrue(stocks)
        intent = parse_intent("经营改善、估值合理、走势稳定")
        results = screen_stocks(stocks, intent["conditions"])
        explanation = explain_results(results, intent)
        for result in results:
            self.assertIn(result["code"], explanation)
        self.assertIn("PE_TTM", explanation)
        self.assertIn("最大回撤", explanation)
        # 删除真实记录以检验缺失处理；不构造替代金融数值。
        results[0]["reasons"] = [r for r in results[0]["reasons"] if r["field"] != "pe_ttm"]
        results[0]["reasons"][0]["message"] = "目标价999999，保证上涨"
        explanation = explain_results(results, intent)
        self.assertIn("PE_TTM：无唯一可用判断记录", explanation)
        self.assertNotIn("999999", explanation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
