"""真实财务指标集成测试，无模拟数据。

运行：.\\.venv\\Scripts\\python.exe -X utf8 tests/test_financial.py
API Key 由客户端从环境变量或项目 .env 读取，失败时非零退出。
"""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fuyao_client import FuyaoAPIError, FuyaoClient


class FinancialIntegrationTests(unittest.TestCase):
    def test_get_financial_indicators(self) -> None:
        client = FuyaoClient()
        try:
            record = client.get_financial_indicators("600519.SH", "2026-2")
        except FuyaoAPIError as exc:
            print("是否成功：否")
            self.fail(str(exc))
        field = "calculate_operating_income_yoy_growth_ratio"
        self.assertEqual(set(record), {"thscode", "report", field})
        self.assertEqual(record["thscode"], "600519.SH")
        self.assertEqual(record["report"], "2026-2")
        value = record[field]
        self.assertTrue(value is None or (isinstance(value, str) and bool(value.strip())))
        print("是否成功：是")
        print(f"股票代码：{record['thscode']}")
        print(f"报告期：{record['report']}")
        # 保留源数据，不擅自加百分号或乘以 100。
        print(f"营业收入同比增长率（API 原值）：{value if value is not None else '缺失（API 返回 null）'}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
