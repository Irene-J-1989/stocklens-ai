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


def parse_legacy_intent(text: str) -> dict:
    """将受支持的短语转换为条件；未知或否定表达不得悄悄执行。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请输入筛选偏好。")
    phrases = [part.strip() for part in re.split(r"[、，,；;\n]+", text) if part.strip()]
    if not phrases or any(phrase not in INTENT_RULES for phrase in phrases):
        raise ValueError("当前规则解析仅支持：经营改善、估值合理、走势相对稳定，请用逗号分隔。")
    conditions = [dict(condition) for phrase in dict.fromkeys(phrases) for condition in INTENT_RULES[phrase]]
    return validate_criteria({"logic": "AND", "conditions": conditions})


def validate_intent(result: dict) -> dict:
    """校验新版意图信封；只接受策略参数，不接受股票事实。"""
    if not isinstance(result, dict) or set(result) != {"conditions", "need_clarification", "conflicts"}:
        raise ValueError("意图结果只能包含 conditions、need_clarification、conflicts。")
    conditions = result["conditions"]
    allowed = {"growth_improvement", "pe_max", "max_drawdown_max"}
    if not isinstance(conditions, dict) or not set(conditions) <= allowed:
        raise ValueError("意图条件包含不支持的字段。")
    if "growth_improvement" in conditions and type(conditions["growth_improvement"]) is not bool:
        raise ValueError("growth_improvement 必须是布尔值。")
    for key in ("pe_max", "max_drawdown_max"):
        if key in conditions and (not is_valid_number(conditions[key]) or conditions[key] <= 0):
            raise ValueError("阈值必须是有限正数。")
    if conditions.get("max_drawdown_max", 0) > 1:
        raise ValueError("最大回撤阈值必须使用 0～1 的比例。")
    if type(result["need_clarification"]) is not bool:
        raise ValueError("need_clarification 必须是布尔值。")
    if not isinstance(result["conflicts"], list) or any(not isinstance(item, str) for item in result["conflicts"]):
        raise ValueError("conflicts 必须是字符串列表。")
    if not result["need_clarification"] and (set(conditions) != allowed or result["conflicts"]):
        raise ValueError("条件不完整或存在冲突时必须先澄清。")
    return result


def parse_intent(text: str) -> dict:
    """本地规则解析，不调用 LLM；未知、否定、部分需求均需澄清。

    支持三类偏好及 PE/最大回撤的严格上限，不自动补充未表达的条件。
    """
    if not isinstance(text, str):
        raise ValueError("选股需求必须是字符串。")
    remaining = re.sub(r"\s+", "", text).replace("％", "%").upper()
    conditions, conflicts = {}, []
    ambiguous = not remaining
    phrases = {
        "经营改善": ("growth_improvement", True),
        "估值合理": ("pe_max", 30), "低估值": ("pe_max", 30),
        "走势相对稳定": ("max_drawdown_max", 0.15),
        "走势稳定": ("max_drawdown_max", 0.15),
    }
    for phrase, (key, threshold) in phrases.items():
        if phrase in remaining:
            conditions[key] = threshold
            remaining = remaining.replace(phrase, "")
    number = r"([0-9]+(?:\.[0-9]+)?)"
    pe_upper = re.compile(r"(?:PE_TTM|PE|市盈率)(?:小于|低于|<)" + number + r"(?:倍)?")
    for match in list(pe_upper.finditer(remaining)):
        value = float(match[1])
        if not is_valid_number(value) or value <= 0:
            ambiguous = True
        else:
            conditions["pe_max"] = min(conditions.get("pe_max", value), value)
        remaining = remaining.replace(match[0], "", 1)
    pe_lower = re.compile(r"(?:PE_TTM|PE|市盈率)(?:超过|大于|高于|>)" + number + r"(?:倍)?")
    for match in list(pe_lower.finditer(remaining)):
        lower = float(match[1])
        if "pe_max" in conditions and lower >= conditions["pe_max"]:
            conflicts.append(f"PE 要求大于 {lower:g}，同时小于 {conditions['pe_max']:g}，无法同时满足。")
        # 当前引擎没有 PE 下限字段，不能静默忽略该要求。
        ambiguous = True
        remaining = remaining.replace(match[0], "", 1)
    drawdown_upper = re.compile(r"最大回撤(?:小于|低于|<)" + number + r"%")
    for match in list(drawdown_upper.finditer(remaining)):
        value = float(match[1]) / 100
        if not is_valid_number(value) or not 0 < value <= 1:
            ambiguous = True
        else:
            conditions["max_drawdown_max"] = min(conditions.get("max_drawdown_max", value), value)
        remaining = remaining.replace(match[0], "", 1)
    if conditions.get("growth_improvement") and re.search(r"(?:营收|营业收入)(?:同比)?(?:下降|负增长)", remaining):
        conflicts.append("经营改善要求营业收入同比大于 0，与营收下降或负增长冲突。")
    # 只移除语气词与连接词，保留否定词、或关系和未知约束以触发澄清。
    remaining = re.sub(r"帮我|请|筛选出|筛选|选出|选择|选|我想要|我想|希望|要求|满足|同时|并且|而且|但是|但|且|和|的股票|股票|[、，,；;。.!！]", "", remaining)
    required = {"growth_improvement", "pe_max", "max_drawdown_max"}
    return validate_intent({"conditions": conditions,
        "need_clarification": bool(ambiguous or remaining or conflicts or set(conditions) != required),
        "conflicts": conflicts})
