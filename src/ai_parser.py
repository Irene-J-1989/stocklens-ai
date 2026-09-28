"""意图解析接口：当前使用规则占位，未来 LLM 只能输出白名单条件。"""

import re

from src.metrics import METRICS, is_valid_number


OPERATORS = {">", ">=", "<", "<=", "=="}
# 以下数值是演示策略参数，不是股票事实，也不构成估值结论。
INTENT_RULES = {
    "经营改善": [
        {"field": "revenue_growth_yoy", "operator": ">", "value": 0},
        {"field": "net_profit_growth_yoy", "operator": ">", "value": 0},
    ],
    "估值合理": [
        {"field": "pe_ttm", "operator": ">", "value": 0},
        {"field": "pe_ttm", "operator": "<=", "value": 30},
    ],
    "走势相对稳定": [
        {"field": "volatility_20d", "operator": ">=", "value": 0},
        {"field": "volatility_20d", "operator": "<=", "value": 3},
    ],
}


def validate_criteria(criteria: dict) -> dict:
    """拒绝额外字段，禁止 AI 输出名称、价格或其他金融事实。"""
    if not isinstance(criteria, dict) or set(criteria) != {"logic", "conditions"}:
        raise ValueError("筛选 JSON 只能包含 logic 和 conditions。")
    if criteria["logic"] != "AND":
        raise ValueError("当前仅支持 AND 筛选。")
    conditions = criteria["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("至少需要一个筛选条件。")
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) != {"field", "operator", "value"}:
            raise ValueError("条件只能包含 field、operator、value。")
        field, operator = condition["field"], condition["operator"]
        if not isinstance(field, str) or field not in METRICS:
            raise ValueError("条件包含不支持的指标。")
        if not isinstance(operator, str) or operator not in OPERATORS:
            raise ValueError("条件包含不支持的比较符。")
        if not is_valid_number(condition["value"]):
            raise ValueError("条件阈值必须是有限数值。")
    return criteria


def parse_intent(text: str) -> dict:
    """将受支持的短语转换为条件；未知或否定表达不得悄悄执行。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请输入筛选偏好。")
    phrases = [part.strip() for part in re.split(r"[、，,；;\n]+", text) if part.strip()]
    if not phrases or any(phrase not in INTENT_RULES for phrase in phrases):
        raise ValueError("当前规则解析仅支持：经营改善、估值合理、走势相对稳定，请用逗号分隔。")
    conditions = [dict(condition) for phrase in dict.fromkeys(phrases) for condition in INTENT_RULES[phrase]]
    return validate_criteria({"logic": "AND", "conditions": conditions})
