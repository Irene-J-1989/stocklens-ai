"""真实日 K 线及最大回撤测试，不使用模拟行情。

运行：.\\.venv\\Scripts\\python.exe -X utf8 tests/test_kline.py
通过 .env 加载密钥；按北京时间排除尚未收盘的当日 K 线。
"""

from datetime import datetime, time, timedelta
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fuyao_client import FuyaoAPIError, FuyaoClient, SHANGHAI_TZ
from src.metrics import calculate_max_drawdown


class KlineIntegrationTests(unittest.TestCase):
    def test_recent_60_trading_days(self) -> None:
        client = FuyaoClient()
        now = datetime.now(SHANGHAI_TZ)
        end = now.date() if now.time() >= time(15) else now.date() - timedelta(days=1)
        try:
            # 自然日只用作取数范围；用 API 返回的实际交易记录确定 60 日窗口。
            for lookback in (120, 240, 365):
                bars = client.get_historical_prices("600519.SH", end - timedelta(days=lookback), end)
                if len(bars) >= 60:
                    break
        except FuyaoAPIError as exc:
            print("是否成功：否")
            self.fail(str(exc))
        self.assertGreaterEqual(len(bars), 60, "近一年内不足 60 根日 K 线，无法计算 60 日最大回撤。")
        recent = bars[-60:]
        dates = [bar["date_ms"] for bar in recent]
        self.assertEqual(dates, sorted(set(dates)))
        prices = [bar["close_price"] for bar in recent]
        drawdown = calculate_max_drawdown(prices)
        # 对同一组真实行情穷举先峰后谷，独立校验单次遍历算法。
        expected = max((prices[i] - prices[j]) / prices[i] for i in range(60) for j in range(i, 60))
        self.assertAlmostEqual(drawdown, expected, places=12)
        self.assertEqual(calculate_max_drawdown(prices[:1]), 0.0)
        first = datetime.fromtimestamp(dates[0] / 1000, SHANGHAI_TZ).date()
        last = datetime.fromtimestamp(dates[-1] / 1000, SHANGHAI_TZ).date()
        print("是否成功：是")
        print("股票代码：600519.SH")
        print(f"实际 K 线范围：{first} 至 {last}")
        print(f"K线数量：{len(recent)}")
        print(f"最新收盘价（前复权）：{prices[-1]}")
        print(f"60日最大回撤：{drawdown:.4%}（比例：{drawdown:.8f}）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
