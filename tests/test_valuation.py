"""真实估值接口测试，不使用模拟数据。

运行：.\\.venv\\Scripts\\python.exe -X utf8 tests/test_valuation.py
需在项目 .env 中配置 FUYAO_API_KEY；请求失败以非零状态退出。
"""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fuyao_client import FuyaoAPIError, FuyaoClient
from src.metrics import is_valid_number


class ValuationIntegrationTests(unittest.TestCase):
    def test_get_valuation_snapshot(self) -> None:
        # 客户端通过 python-dotenv 加载 .env，不打印 API Key。
        client = FuyaoClient()
        try:
            records = client.get_valuation_snapshot("600519.SH")
        except FuyaoAPIError as exc:
            print("是否成功：否")
            self.fail(str(exc))
        self.assertEqual(len(records), 1, "接口未返回所请求股票的唯一估值记录。")
        stock = records[0]
        self.assertEqual(set(stock), {"thscode", "name", "pe_ttm"})
        self.assertEqual(stock["thscode"], "600519.SH")
        self.assertTrue(stock["name"] is None or isinstance(stock["name"], str))
        self.assertTrue(stock["pe_ttm"] is None or is_valid_number(stock["pe_ttm"]))
        print("是否成功：是")
        print(f"股票代码：{stock['thscode']}")
        print(f"股票名称：{stock['name'] if stock['name'] is not None else '缺失（API 返回 null）'}")
        print(f"PE_TTM：{stock['pe_ttm'] if stock['pe_ttm'] is not None else '缺失（API 返回 null）'}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
