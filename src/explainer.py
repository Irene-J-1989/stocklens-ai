"""解释接口：模板仅引用条件和筛选统计，不生成金融事实。"""

from src.ai_parser import validate_criteria
from src.metrics import METRICS


def explain_conditions(criteria: dict) -> str:
    validate_criteria(criteria)
    descriptions = []
    for condition in criteria["conditions"]:
        metric = METRICS[condition["field"]]
        descriptions.append(f"{metric['label']} {condition['operator']} {condition['value']}{metric['unit']}")
    return "同时满足：" + "；".join(descriptions) + "。阈值仅用于演示策略，尚未进行行业适配。"


def explain_results(results: list[dict], criteria: dict) -> str:
    validate_criteria(criteria)
    return f"根据本地缓存，有 {len(results)} 条记录满足全部条件。参与筛选的指标缺失时，该记录会被排除。"
