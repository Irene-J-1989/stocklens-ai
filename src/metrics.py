"""内部字段约定，不代表扶摇 API 的真实字段；接入时需显式映射。"""

from math import isfinite


METRICS = {
    "revenue_growth_yoy": {"label": "营收同比增长率", "unit": "%"},
    "net_profit_growth_yoy": {"label": "净利润同比增长率", "unit": "%"},
    "pe_ttm": {"label": "滚动市盈率", "unit": "倍"},
    "volatility_20d": {"label": "20 日波动率", "unit": "%"},
}


def is_valid_number(value: object) -> bool:
    """缺失、布尔、字符串以及非有限数值不能参与金融筛选。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def calculate_max_drawdown(prices: list[float]) -> float:
    """按时间升序的收盘价计算最大回撤，返回非负比例（0.1 表示 10%）。

    回撤 = (此前峰值 - 当前价格) / 此前峰值；仅基于输入窗口内的价格。
    单个价格返回 0；空列表、缺失值及非正价格报错，不补零或跳过。
    """
    if not isinstance(prices, list) or not prices:
        raise ValueError("prices 必须是非空的收盘价列表。")
    peak = 0.0
    max_drawdown = 0.0
    for price in prices:
        if not is_valid_number(price) or price <= 0:
            raise ValueError("每个收盘价必须是有限正数，不能包含缺失值。")
        peak = max(peak, price)
        max_drawdown = max(max_drawdown, (peak - price) / peak)
    return max_drawdown
