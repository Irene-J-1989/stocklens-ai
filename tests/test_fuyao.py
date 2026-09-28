"""真实联网集成测试：需配置 FUYAO_API_KEY，不使用模拟数据。

运行：.\\.venv\\Scripts\\python.exe tests/test_fuyao.py
失败时打印明确错误，并通过 unittest 返回非零退出码。
"""

import os
from pathlib import Path
import sys
import unittest

# 支持从项目根目录直接运行该测试文件。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from src.fuyao_client import FuyaoAPIError, FuyaoClient


class FuyaoIntegrationTests(unittest.TestCase):
    def test_get_hs300_components(self) -> None:
        load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8-sig")
        print(f"环境变量已配置：{bool(os.getenv('FUYAO_API_KEY', '').strip())}")
        client = FuyaoClient()
        try:
            components = client.get_hs300_components()
        except FuyaoAPIError as exc:
            print("是否成功：否")
            print("股票数量：未知（请求失败）")
            print("前5只股票：不可用")
            self.fail(str(exc))
        self.assertGreater(len(components), 0)
        for component in components:
            self.assertEqual(set(component), {"thscode", "name"})
        print("是否成功：是")
        print(f"股票数量：{len(components)}")
        print("前5只股票：")
        for component in components[:5]:
            print(f"  {component['thscode']}  {component['name']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
