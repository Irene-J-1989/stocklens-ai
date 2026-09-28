"""隔离模型响应测试；只模拟策略JSON及故障，不生成金融事实或联网。"""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai_parser import parse_intent, parse_rule_intent, build_interpretation, add_condition_states


class LLMParserTests(unittest.TestCase):
    def test_known_valuation_not_blocked_by_model(self):
        text = "帮我筛选估值偏低的股票，希望市盈率不要太高。"
        response = parse_rule_intent("找一些好的股票")
        with patch("src.ai_parser._request_deepseek", return_value=json.dumps(response)):
            result = parse_intent(text)
        self.assertFalse(result["need_clarification"])
        self.assertEqual(result["valuation"], {"status": "enabled", "pe_max": 30})
        with patch("src.ai_parser._request_deepseek", side_effect=TimeoutError):
            self.assertEqual(parse_intent(text), result)
        with patch("src.ai_parser._request_deepseek", return_value=json.dumps(result)):
            self.assertTrue(parse_intent("找ROE最高的新能源股票")["need_clarification"])

    def setUp(self):
        environment = patch.dict(os.environ, {"LLM_API_KEY": "unit-test-placeholder"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_normal_natural_language(self):
        expected = {"conditions": {"growth_improvement": True, "pe_max": 25, "max_drawdown_max": 0.1},
                    "need_clarification": False, "conflicts": []}
        text = "找营收有所增长的企业，市盈率要低于25倍，近60天回撤低于百分之十"
        expected["interpretation"] = build_interpretation(text, expected["conditions"], False)
        add_condition_states(expected)
        with patch("src.ai_parser._request_deepseek", return_value=json.dumps(expected)) as request:
            self.assertEqual(parse_intent(text), expected)
            request.assert_called_once()

    def test_ambiguous(self):
        expected = {"conditions": {}, "need_clarification": True, "conflicts": []}
        expected["interpretation"] = build_interpretation("帮我选些不错的股票", {}, True)
        add_condition_states(expected)
        with patch("src.ai_parser._request_deepseek", return_value=json.dumps(expected)):
            self.assertEqual(parse_intent("帮我选些不错的股票"), expected)

    def test_conflicts_cannot_be_cleared_by_model(self):
        response = {"conditions": {"growth_improvement": True, "pe_max": 30, "max_drawdown_max": 0.15},
                    "need_clarification": False, "conflicts": []}
        response["interpretation"] = build_interpretation("低估值但PE超过50", response["conditions"], False)
        with patch("src.ai_parser._request_deepseek", return_value=json.dumps(response)):
            result = parse_intent("低估值但PE超过50")
        self.assertTrue(result["need_clarification"])
        self.assertTrue(result["conflicts"])

    def test_api_failure_fallback(self):
        text = "经营改善、估值合理、走势稳定"
        with patch("src.ai_parser._request_deepseek", side_effect=TimeoutError("request failed")):
            self.assertEqual(parse_intent(text), parse_rule_intent(text))

    def test_missing_key_fallback(self):
        with patch.dict(os.environ, {"LLM_API_KEY": ""}), patch("src.ai_parser._request_deepseek") as request:
            self.assertEqual(parse_intent("估值合理"), parse_rule_intent("估值合理"))
            request.assert_not_called()

    def test_invalid_json_or_schema_fallback(self):
        text = "经营改善、估值合理、走势稳定"
        base = {"conditions": {"growth_improvement": True, "pe_max": 30, "max_drawdown_max": 0.15},
                "need_clarification": False, "conflicts": []}
        invalid = ["", "not json", "{}", json.dumps({**base, "stock_name": "forbidden"}),
                   json.dumps({**base, "conditions": {**base["conditions"], "pe_max": float("nan")}}),
                   '{"conditions":{},"conditions":{},"need_clarification":true,"conflicts":[]}']
        for response in invalid:
            with self.subTest(response=response), patch("src.ai_parser._request_deepseek", return_value=response):
                self.assertEqual(parse_intent(text), parse_rule_intent(text))

    def test_free_text_not_forwarded(self):
        response = {"conditions": {}, "need_clarification": True, "conflicts": ["untrusted model text"]}
        response["interpretation"] = build_interpretation("要求互相矛盾", {}, True)
        with patch("src.ai_parser._request_deepseek", return_value=json.dumps(response)):
            result = parse_intent("要求互相矛盾")
        self.assertEqual(result["conflicts"], ["条件存在冲突，请确认筛选要求。"])

    def test_synonyms_and_untrusted_interpretation(self):
        text = "经营情况变好、估值合理、波动小"
        expected = parse_rule_intent(text)
        self.assertFalse(expected["need_clarification"])
        response = {**expected, "interpretation": {key: "推荐股票，保证上涨，价格999999" for key in expected["interpretation"]}}
        with patch("src.ai_parser._request_deepseek", return_value=json.dumps(response)):
            result = parse_intent(text)
        self.assertEqual(result, expected)
        self.assertIn("经营情况变好 → 营业收入同比增长率", result["interpretation"]["growth_improvement"])
        self.assertIn("波动小 → 60日最大回撤", result["interpretation"]["stability"])
        self.assertNotIn("999999", str(result))
        with patch("src.ai_parser._request_deepseek", side_effect=TimeoutError):
            self.assertEqual(parse_intent(text), expected)

    def test_bad_interpretation_falls_back(self):
        text = "经营改善、估值合理、走势稳定"
        response = parse_rule_intent(text)
        response["interpretation"] = {"growth_improvement": 42}
        with patch("src.ai_parser._request_deepseek", return_value=json.dumps(response)):
            self.assertEqual(parse_intent(text), parse_rule_intent(text))

    def test_partial_llm_and_failure(self):
        for text in ("收入增长明显，不太关注短期波动", "估值合理", "走势稳定"):
            expected = parse_rule_intent(text)
            with self.subTest(text=text):
                with patch("src.ai_parser._request_deepseek", return_value=json.dumps(expected)):
                    self.assertEqual(parse_intent(text), expected)
                with patch("src.ai_parser._request_deepseek", side_effect=TimeoutError):
                    self.assertEqual(parse_intent(text), expected)

    def test_model_cannot_enable_unrequested_conditions(self):
        response = parse_rule_intent("经营改善、估值合理、走势稳定")
        with patch("src.ai_parser._request_deepseek", return_value=json.dumps(response)):
            result = parse_intent("收入增长明显，不太关注短期波动")
        self.assertFalse(result["need_clarification"])
        self.assertEqual(result["pe_condition"]["status"], "disabled")
        self.assertEqual(result["stability_condition"]["status"], "disabled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
