"""使用纯合成数值验证逻辑；测试记录不进入产品数据缓存。"""

import unittest

from src.ai_parser import parse_legacy_intent as parse_intent, validate_criteria
from src.screener import screen_stocks


class ScreeningTests(unittest.TestCase):
    def test_and_boundaries_and_missing_values(self):
        criteria = parse_intent("经营改善、估值合理、走势相对稳定")
        passing = {"revenue_growth_yoy": 1, "net_profit_growth_yoy": 1, "pe_ttm": 30, "volatility_20d": 3}
        records = [passing, {**passing, "pe_ttm": 0}, {**passing, "volatility_20d": None}, {**passing, "revenue_growth_yoy": 0}]
        self.assertEqual(screen_stocks(records, criteria), [passing])

    def test_rejects_unknown_and_negated_intent(self):
        for text in ("", "不要求经营改善", "经营改善、随便选"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_intent(text)

    def test_rejects_financial_facts_in_ai_output(self):
        criteria = parse_intent("估值合理")
        criteria["stock_name"] = "不得由模型输出"
        with self.assertRaises(ValueError):
            validate_criteria(criteria)

    def test_rejects_nonfinite_threshold(self):
        criteria = parse_intent("估值合理")
        criteria["conditions"][0]["value"] = float("nan")
        with self.assertRaises(ValueError):
            validate_criteria(criteria)


if __name__ == "__main__":
    unittest.main()
