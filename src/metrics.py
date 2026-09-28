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
