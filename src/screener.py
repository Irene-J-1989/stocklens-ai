"""确定性筛选引擎：仅比较输入数据，不调用 AI 或补全金融事实。"""

import operator

from src.metrics import is_valid_number


COMPARATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq}


def _screen_legacy(stocks: list[dict], criteria: dict) -> list[dict]:
    """兼容现有页面的白名单 JSON；只进行确定性比较。"""
    from src.ai_parser import validate_criteria

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


def _number(value: object) -> int | float | None:
    """将 API 数值字符串转换为数值；缺失、布尔和非有限值不参与比较。"""
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    return value if is_valid_number(value) else None


def screen_stocks(stock_data: list[dict], conditions: dict) -> list[dict]:
    """逐只判断三项条件，返回 code/name/selected/reasons/failed_conditions。

    股票字段为 code、name、revenue_growth_yoy、pe_ttm、max_drawdown。
    兼容流水线字段 revenue_yoy、代码字段 thscode/symbol 和 API 原始营收增长率字段。
    最大回撤使用比例（0.15 = 15%），营收增速仅比较正负，不换算单位。
    reasons 保存每项的原值、阈值、是否启用、是否通过和说明；
    failed_conditions 保存未通过的条件名。关闭条件的 passed 为 None。
    旧版 logic/conditions JSON 仍返回入选原记录，供现有页面使用。
    """
    if not isinstance(conditions, dict):
        raise ValueError("conditions 必须是对象。")
    if "logic" in conditions or "conditions" in conditions:
        return _screen_legacy(stock_data, conditions)
    required = {"growth_improvement", "pe_max", "max_drawdown_max"}
    if set(conditions) != required:
        raise ValueError("条件必须包含且仅包含 growth_improvement、pe_max、max_drawdown_max。")
    if type(conditions["growth_improvement"]) is not bool:
        raise ValueError("growth_improvement 必须是布尔值。")
    if not is_valid_number(conditions["pe_max"]) or conditions["pe_max"] <= 0:
        raise ValueError("pe_max 必须是有限正数。")
    if not is_valid_number(conditions["max_drawdown_max"]) or not 0 <= conditions["max_drawdown_max"] <= 1:
        raise ValueError("max_drawdown_max 必须是 0～1 的比例。")
    if not isinstance(stock_data, list):
        raise ValueError("stock_data 必须是股票记录列表。")
    results = []
    for stock in stock_data:
        if not isinstance(stock, dict):
            raise ValueError("每条股票数据必须是对象。")
        code = stock.get("code", stock.get("thscode", stock.get("symbol")))
        name = stock.get("name")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("股票数据缺少有效代码。")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValueError("股票名称必须是非空字符串或 None。")
        growth_field = next((field for field in (
            "revenue_yoy", "revenue_growth_yoy", "calculate_operating_income_yoy_growth_ratio"
        ) if field in stock), "revenue_yoy")
        rules = [
            ("growth_improvement", growth_field, ">", 0, conditions["growth_improvement"], "经营改善"),
            ("pe_max", "pe_ttm", "<", conditions["pe_max"], True, "估值合理"),
            ("max_drawdown_max", "max_drawdown", "<", conditions["max_drawdown_max"], True, "走势稳定"),
        ]
        reasons, failed = [], []
        for key, field, comparison, threshold, enabled, label in rules:
            raw_value = stock.get(field)
            value = _number(raw_value)
            passed = None
            if not enabled:
                message = f"{label}：未启用。"
            elif value is None or (field == "max_drawdown" and not 0 <= value <= 1):
                passed = False
                message = f"{label}：指标缺失或非法，未通过。"
            else:
                passed = COMPARATORS[comparison](value, threshold)
                message = f"{label}：{value} {comparison} {threshold}，{'通过' if passed else '未通过'}。"
            reasons.append({
                "condition": key, "field": field, "value": raw_value,
                "operator": comparison, "threshold": threshold,
                "enabled": enabled, "passed": passed, "message": message,
            })
            if enabled and not passed:
                failed.append(key)
        results.append({"code": code, "name": name, "selected": not failed,
                        "reasons": reasons, "failed_conditions": failed})
    return results
