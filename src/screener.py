"""确定性筛选引擎：仅比较输入数据，不调用 AI 或补全金融事实。"""

import operator

from src.ai_parser import validate_criteria
from src.metrics import is_valid_number


COMPARATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq}


def screen_stocks(stocks: list[dict], criteria: dict) -> list[dict]:
    """所有条件均满足才入选；参与筛选的指标缺失时排除该记录。"""
    validate_criteria(criteria)
    results = []
    for stock in stocks:
        matched = True
        for condition in criteria["conditions"]:
            value = stock.get(condition["field"])
            if not is_valid_number(value) or not COMPARATORS[condition["operator"]](value, condition["value"]):
                matched = False
                break
        if matched:
            results.append(dict(stock))
    return results
