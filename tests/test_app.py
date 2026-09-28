"""使用已有真实 CSV 的页面交互测试，不联网或刷新数据。"""

from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
