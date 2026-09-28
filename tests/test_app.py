"""使用已有真实 CSV 的页面交互测试，不联网或刷新数据。"""

from pathlib import Path
import os
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    def setUp(self):
        # 页面回归固定走规则回退，避免因本机密钥产生网络请求和不确定结果。
        environment = patch.dict(os.environ, {"LLM_API_KEY": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def app(self):
        return AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)

    def test_clarification_blocks_execution(self):
        app = self.app()
        app.text_area[0].set_value("低估值但PE超过50")
        app.button(key="parse").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.warning)
        self.assertTrue(app.error)
        self.assertEqual(len(app.number_input), 0)
        self.assertNotIn("execute", [button.key for button in app.button])

    def test_screen_edit_and_detail(self):
        if not (ROOT / "data" / "stock_dataset.csv").exists():
            self.skipTest("需先生成真实缓存。")
        app = self.app()
        app.button(key="parse").click().run()
        app.button(key="execute").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(list(app.dataframe[0].value.columns), ["股票名称", "代码", "PE_TTM", "营业收入同比", "最大回撤", "是否入选"])
        count = len(app.dataframe[0].value)
        self.assertGreater(count, 0)
        if count > 1:
            app.selectbox[0].set_value(1).run()
            self.assertFalse(app.exception)
            self.assertIn(app.dataframe[0].value.iloc[1]["代码"], app.subheader[-1].value)
        app.number_input(key="pe_limit").set_value(1.0).run()
        self.assertEqual(len(app.dataframe), 0)
        app.button(key="execute").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["run"]["intent"]["conditions"]["pe_max"], 1.0)
        app.text_area[0].set_value("走势稳定").run()
        self.assertEqual(len(app.dataframe), 0)
        self.assertTrue(app.warning)

    def test_missing_cache(self):
        app = self.app()
        app.button(key="parse").click().run()
        with patch.object(pd, "read_csv", side_effect=FileNotFoundError):
            app.button(key="execute").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertEqual(len(app.dataframe), 0)

    def test_condition_comparison_and_failed_retry(self):
        if not (ROOT / "data" / "stock_dataset.csv").exists():
            self.skipTest("需先生成真实缓存。")
        app = self.app()
        app.button(key="parse").click().run()
        app.button(key="execute").click().run(timeout=30)
        baseline = app.session_state["run"]
        self.assertNotIn("comparison", baseline)
        old = {item["code"] for item in baseline["results"] if item["selected"]}
        app.number_input(key="pe_limit").set_value(1.0).run()
        app.number_input(key="drawdown_limit").set_value(1.0).run()
        self.assertEqual(app.session_state["last_successful_run"]["id"], baseline["id"])
        with patch.object(pd, "read_csv", side_effect=FileNotFoundError):
            app.button(key="execute").click().run()
        self.assertEqual(app.session_state["last_successful_run"]["id"], baseline["id"])
        app.button(key="execute").click().run(timeout=30)
        self.assertFalse(app.exception)
        current = app.session_state["run"]
        new = {item["code"] for item in current["results"] if item["selected"]}
        comparison = current["comparison"]
        self.assertEqual(comparison["before_count"], len(old))
        self.assertEqual(comparison["after_count"], len(new))
        self.assertEqual(set(comparison["added"]), new - old)
        self.assertEqual(set(comparison["removed"]), old - new)
        self.assertEqual(len(comparison["changes"]), 2)
        self.assertTrue(comparison["same_data"])
        self.assertIn("共同作用", comparison["explanation"])
        app.number_input(key="pe_limit").set_value(30.0).run()
        app.number_input(key="drawdown_limit").set_value(15.0).run()
        app.button(key="execute").click().run()
        restored = app.session_state["run"]["comparison"]
        self.assertEqual(restored["before_count"], len(new))
        self.assertEqual(set(restored["added"]), old - new)
        app.button(key="execute").click().run()
        unchanged = app.session_state["run"]["comparison"]
        self.assertEqual(unchanged["added"], [])
        self.assertEqual(unchanged["removed"], [])
        # 用真实缓存的子集模拟股票池变动，不能误称是阈值导致。
        reduced = baseline["frame"].iloc[:-1].copy()
        if not reduced.empty:
            with patch.object(pd, "read_csv", return_value=reduced):
                app.button(key="execute").click().run()
            changed_data = app.session_state["run"]["comparison"]
            self.assertFalse(changed_data["same_data"])
            self.assertIn("不能仅归因", changed_data["explanation"])
        app.text_area[0].set_value("估值合理").run()
        self.assertNotIn("last_successful_run", app.session_state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
