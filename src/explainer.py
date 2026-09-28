"""解释接口：模板仅引用条件和筛选统计，不生成金融事实。"""

from src.ai_parser import validate_criteria, validate_intent
from src.metrics import METRICS, is_valid_number


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
