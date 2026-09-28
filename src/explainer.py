"""解释接口：模板仅引用条件和筛选统计，不生成金融事实。"""

from src.ai_parser import validate_criteria, validate_intent
from src.metrics import METRICS, is_valid_number


def build_result_cards(result: dict) -> list[dict]:
    """将已有逐项判断转为展示卡片；不读 message、不查询或生成金融数据。"""
    definitions = [
        ("growth_improvement", "revenue_yoy", "经营改善", "营业收入同比增长率"),
        ("pe_max", "pe_ttm", "估值合理", "PE(TTM)"),
        ("max_drawdown_max", "max_drawdown", "走势稳定", "60日最大回撤"),
    ]
    cards = []
    for key, field, title, label in definitions:
        matches = [r for r in result.get("reasons", []) if isinstance(r, dict)
                   and r.get("condition") == key and r.get("field") == field]
        reason = matches[0] if len(matches) == 1 else {}
        enabled = reason.get("enabled") is not False
        passed = reason.get("passed") if type(reason.get("passed")) is bool else None
        value = reason.get("value")
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                value = None
        valid = is_valid_number(value) and (field != "max_drawdown" or 0 <= value <= 1)
        data_text = "数据缺失或不可用"
        if valid:
            data_text = f"{value:.2%}" if field == "max_drawdown" else f"{value:.2f}" + ("%" if field == "revenue_yoy" else "")
        threshold = reason.get("threshold")
        comparison = reason.get("operator")
        requirement = "未提供有效筛选要求"
        if is_valid_number(threshold) and comparison in ("<", ">", "<=", ">=", "=="):
            threshold_text = f"{threshold * 100:g}%" if field == "max_drawdown" else f"{threshold:g}" + ("%" if field == "revenue_yoy" else "")
            requirement = f"{label} {comparison} {threshold_text}"
        if not enabled:
            status, explanation = "未启用", "本次未启用该条件，不计入条件匹配数量。"
        elif not reason or passed is None:
            status, explanation = "待核对", "缺少唯一有效判断记录，无法说明该条件是否满足。"
        elif not valid:
            status, explanation = "未满足", "当前指标缺失或不可用，无法确认符合要求，因此未满足该条件。"
        else:
            status = "已满足" if passed else "未满足"
            if field == "revenue_yoy":
                explanation = ("当前营业收入同比增长，满足经营改善条件。" if passed else
                               "当前营业收入同比下降，因此未满足经营改善条件。" if value < 0 else
                               "当前营业收入同比没有增长，因此未满足经营改善条件。")
            elif field == "pe_ttm":
                explanation = ("当前市盈率低于设定上限，满足估值筛选条件。" if passed else
                               "当前市盈率达到或超过设定上限，因此未满足估值筛选条件。")
            else:
                explanation = ("最近60日最大回撤低于设定上限，满足走势稳定条件。" if passed else
                               "最近60日最大回撤达到或超过设定上限，因此未满足走势稳定条件。")
        cards.append({"title": title, "label": label, "value": data_text,
                      "requirement": requirement, "explanation": explanation,
                      "enabled": enabled, "passed": passed if valid else False if reason else None,
                      "status": status})
    return cards


def explain_conditions(criteria: dict) -> str:
    if "logic" not in criteria:
        validate_intent(criteria)
        if criteria["need_clarification"]:
            return "需要澄清，暂不执行筛选。" + ("；".join(criteria["conflicts"]) or "请明确经营改善、PE上限及最大回撤上限，并确认未识别的表达。")
        conditions = criteria["conditions"]
        growth = "营业收入同比 > 0" if conditions["growth_improvement"] else "不启用经营改善条件"
        return (f"{growth}；PE_TTM < {conditions['pe_max']:g}；最大回撤 < {conditions['max_drawdown_max']:.2%}。"
                "语义默认阈值为 PE < 30、最大回撤 < 15%，属于策略参数。")
    validate_criteria(criteria)
    descriptions = []
    for condition in criteria["conditions"]:
        metric = METRICS[condition["field"]]
        descriptions.append(f"{metric['label']} {condition['operator']} {condition['value']}{metric['unit']}")
    return "同时满足：" + "；".join(descriptions) + "。阈值仅用于演示策略，尚未进行行业适配。"


def explain_results(results: list[dict], criteria: dict) -> str:
    """仅引用 reasons 中白名单指标的原值和判断，不采用自由文本 message。"""
    if "logic" in criteria:
        validate_criteria(criteria)
        return f"根据本地缓存，有 {len(results)} 条记录满足全部条件。"
    validate_intent(criteria)
    if criteria["need_clarification"]:
        raise ValueError("需求尚未澄清，不能生成筛选结果解释。")
    labels = {"revenue_yoy": "营业收入同比（数据原值）", "pe_ttm": "PE_TTM", "max_drawdown": "最大回撤"}
    lines = []
    for result in results:
        if type(result.get("selected")) is not bool:
            raise ValueError("筛选结果缺少有效 selected 状态。")
        identity = " ".join(str(result[key]) for key in ("code", "name") if result.get(key)) or "未提供股票标识"
        details = []
        for field, label in labels.items():
            matching = [r for r in result.get("reasons", []) if isinstance(r, dict) and r.get("field") == field]
            if len(matching) != 1:
                details.append(f"{label}：无唯一可用判断记录")
                continue
            reason = matching[0]
            value = reason.get("value")
            if isinstance(value, str):
                try:
                    value = float(value)
                except ValueError:
                    value = None
            if not is_valid_number(value):
                rendered = "缺失或非法"
            else:
                rendered = f"{value:.4%}" if field == "max_drawdown" else str(value)
            status = "未启用" if reason.get("enabled") is False else (
                "通过" if reason.get("passed") is True else "未通过" if reason.get("passed") is False else "无判断")
            details.append(f"{label}：{rendered}（{status}）")
        lines.append(f"{identity}：{'入选' if result['selected'] else '未入选'}。" + "；".join(details) + "。")
    selected = sum(result["selected"] for result in results)
    return f"共评估 {len(results)} 只股票，入选 {selected} 只。\n" + "\n".join(lines)
