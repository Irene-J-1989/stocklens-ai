"""StockLens AI：解析、确认条件、读取本地真实缓存、展示规则匹配。"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.ai_parser import parse_intent
from src.explainer import build_result_cards
from src.screener import screen_stocks


DATASET_PATH = Path(__file__).resolve().parent / "data" / "stock_dataset.csv"
COLUMNS = ["code", "name", "pe_ttm", "revenue_yoy", "max_drawdown"]
CONDITION_LABELS = {"growth_improvement": "经营改善", "pe_max": "估值合理", "max_drawdown_max": "走势稳定"}


def load_dataset() -> pd.DataFrame:
    """每次执行重新读取缓存；非法数值保留缺失，由引擎判定未通过。"""
    frame = pd.read_csv(DATASET_PATH, encoding="utf-8-sig", dtype={"code": str, "name": str})
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError("缓存缺少字段：" + "、".join(sorted(missing)))
    if frame.empty:
        raise ValueError("股票缓存为空，请先生成股票数据集。")
    if frame[["code", "name"]].isna().any().any() or frame["code"].duplicated().any():
        raise ValueError("缓存包含缺失的股票标识或重复代码，请重新生成数据集。")
    frame = frame[COLUMNS].copy()
    for field in ("pe_ttm", "revenue_yoy", "max_drawdown"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce").replace([float("inf"), -float("inf")], float("nan"))
    return frame


def compare_runs(before: dict, after: dict) -> dict:
    """按股票代码集合比较两次成功筛选；缓存不同不归因于阈值变化。"""
    old_codes = {item["code"] for item in before["results"] if item["selected"]}
    new_codes = {item["code"] for item in after["results"] if item["selected"]}
    old_conditions, new_conditions = before["intent"]["conditions"], after["intent"]["conditions"]
    changes = []
    for key, label in (("pe_max", "PE限制"), ("max_drawdown_max", "最大回撤限制")):
        old, new = old_conditions[key], new_conditions[key]
        if old != new:
            if old is None or new is None:
                changes.append(f"{'关闭' if new is None else '启用'}{label}")
                continue
            values = f"{old:g} → {new:g}" if key == "pe_max" else f"{old:.2%} → {new:.2%}"
            changes.append(f"{'放宽' if new > old else '收紧'}{label}（{values}）")
    same_data = before["frame"].sort_values("code").reset_index(drop=True).equals(
        after["frame"].sort_values("code").reset_index(drop=True))
    added, removed = sorted(new_codes - old_codes), sorted(old_codes - new_codes)
    delta = len(new_codes) - len(old_codes)
    outcome = f"候选数量{'增加' if delta > 0 else '减少'} {abs(delta)} 只" if delta else "候选数量不变"
    if not same_data:
        explanation = f"两次筛选的数据缓存发生变化，{outcome}。本次变化不能仅归因于条件调整。"
    elif not changes:
        explanation = f"筛选条件未变化，{outcome}。"
    else:
        explanation = "、".join(changes) + f"后，{outcome}。"
        if len(changes) > 1:
            explanation += "这是多项条件共同作用的结果。"
        elif added and not removed:
            explanation += "更多股票满足调整后的限制，同时满足其他启用条件，因此进入候选范围。"
        elif removed and not added:
            explanation += "部分原候选股票不再满足调整后的限制，因此退出候选范围。"
        elif not added and not removed:
            explanation += "本次调整未改变满足全部条件的股票集合。"
    return {"before_count": len(old_codes), "after_count": len(new_codes),
            "added": added, "removed": removed, "same_data": same_data,
            "changes": changes, "explanation": explanation}


def show_results(run: dict) -> None:
    """表格和详情始终使用同一次已确认筛选快照，避免重跑后错配。"""
    frame, results = run["frame"], run["results"]
    st.subheader("4. 规则匹配结果")
    comparison = run.get("comparison")
    if comparison is not None:
        with st.container(border=True):
            st.markdown("**条件变化影响分析**")
            for column, label, count in zip(st.columns(4),
                ("调整前候选数量", "调整后候选数量", "新增数量", "减少数量"),
                (comparison["before_count"], comparison["after_count"], len(comparison["added"]), len(comparison["removed"]))):
                column.metric(label, count)
            st.write(comparison["explanation"])
            st.caption("与本轮需求下上一次成功筛选对比；新增、减少按股票代码计算。")
    selected_count = sum(item["selected"] for item in results)
    st.write(f"共 {len(results)} 只 · 入选 {selected_count} 只 · 未入选 {len(results) - selected_count} 只")
    if selected_count == 0:
        st.info("没有股票满足全部条件。可调整阈值后重新筛选。")
    st.caption(run["source_caption"])
    st.caption("表格保留所有股票；缺失指标显示为空，启用的条件遇到缺失值会判为未通过。最大回撤为最近60根前复权日K线口径。")
    display = frame[["name", "code", "pe_ttm", "revenue_yoy", "max_drawdown"]].copy()
    display["max_drawdown"] *= 100
    display["selected"] = ["是" if item["selected"] else "否" for item in results]
    display.columns = ["股票名称", "代码", "PE_TTM", "营业收入同比", "最大回撤", "是否入选"]
    event = st.dataframe(
        display, hide_index=True, use_container_width=True,
        on_select="rerun", selection_mode="single-row", key=f"table_{run['id']}",
        column_config={
            "PE_TTM": st.column_config.NumberColumn(format="%.4f"),
            "营业收入同比": st.column_config.NumberColumn(help="扶摇API原值，未额外换算单位", format="%.4f"),
            "最大回撤": st.column_config.NumberColumn(help="以百分比展示，筛选引擎使用0～1比例", format="%.2f%%"),
        },
    )
    st.caption("点击表格中的一行查看详情，也可使用下方股票选择框。")
    if event.selection.rows:
        index = event.selection.rows[0]
    else:
        index = st.selectbox("查看股票详情", range(len(results)),
                             format_func=lambda i: f"{results[i]['name']} · {results[i]['code']}",
                             key=f"detail_{run['id']}")
    result = results[index]
    st.subheader(f"{result['name']} · {result['code']}")
    cards = build_result_cards(result)
    enabled = [card for card in cards if card["enabled"]]
    passed = [card for card in enabled if card["passed"] is True]
    failed = [card for card in enabled if card["passed"] is False]
    st.metric("条件匹配", f"{len(passed)}/{len(enabled)}")
    st.write("✅ 入选：满足全部启用条件。" if result["selected"] else "未入选：尚未满足全部启用条件。")
    left, right = st.columns(2)
    with left:
        st.markdown("**已通过**")
        for card in passed:
            st.write(f"✅ {card['title']}")
        if not passed:
            st.write("暂无已通过条件")
    with right:
        st.markdown("**未通过**")
        for card in failed:
            st.write(f"❌ {card['title']}")
        if not failed:
            st.write("无")
    st.markdown("**条件匹配情况**")
    for column, card in zip(st.columns(3), cards):
        with column:
            with st.container(border=True):
                icon = "✅" if card["status"] == "已满足" else "❌" if card["status"] == "未满足" else "➖"
                st.markdown(f"**{icon} {card['title']}{card['status']}**")
                st.caption("当前数据")
                st.write(f"{card['label']}：{card['value']}")
                st.caption("筛选要求")
                st.write(card["requirement"])
                st.caption("原因")
                st.write(card["explanation"])
    st.caption("数值按两位小数展示，规则匹配使用原始精度。AI负责解释投资意图；规则引擎负责筛选；金融数据提供事实。")


def main() -> None:
    st.set_page_config(page_title="StockLens AI", page_icon="📊", layout="wide")
    st.title("StockLens AI")
    st.caption("用自然语言描述偏好，查看股票与条件的匹配情况")
    st.info("AI负责理解你的投资意图，实际筛选基于真实金融数据和确定性规则。")
    st.caption("仅展示规则匹配结果，不提供买入建议或涨跌预测。")
    st.subheader("1. 描述选股需求")
    query = st.text_area("自然语言选股需求", "经营改善、估值合理、走势稳定", key="query")
    if st.button("解析需求", key="parse", type="primary"):
        st.session_state.pop("run", None)
        st.session_state.pop("last_successful_run", None)
        intent = parse_intent(query)
        st.session_state["intent"] = intent
        st.session_state["parsed_query"] = query
        st.session_state["pe_limit"] = float(intent["conditions"].get("pe_max") or 30)
        st.session_state["drawdown_limit"] = float(intent["conditions"].get("max_drawdown_max") or 0.15) * 100
    if "intent" not in st.session_state:
        return
    if query != st.session_state["parsed_query"]:
        st.session_state.pop("run", None)
        st.session_state.pop("last_successful_run", None)
        st.warning("需求已修改，请重新解析后再确认条件。")
        return
    intent = st.session_state["intent"]
    st.subheader("AI理解你的需求")
    conditions = intent["conditions"]
    growth_status = intent["growth_condition"]["status"]
    pe_status = intent["pe_condition"]["status"]
    stability_status = intent["stability_condition"]["status"]
    # 展示当前编辑中的阈值；原始解析结果留在折叠区，不改写解析或筛选逻辑。
    growth = conditions.get("growth_improvement")
    growth_text = "营业收入同比增长率 > 0%" if growth is True else "未启用经营改善条件" if growth is False else "待补充经营改善要求"
    pe_text = (f"PE(TTM) < {st.session_state['pe_limit']:g}"
               if "pe_max" in conditions else "待确认 PE(TTM) 上限")
    drawdown_text = (f"60日最大回撤 < {st.session_state['drawdown_limit']:g}%"
                     if "max_drawdown_max" in conditions else "待确认最大回撤上限")
    growth_text, pe_text, drawdown_text = [
        "未启用" if status == "disabled" else "待澄清" if status == "unknown" else description
        for status, description in zip((growth_status, pe_status, stability_status), (growth_text, pe_text, drawdown_text))
    ]
    for column, title, description in zip(
        st.columns(3), ("经营改善", "估值合理", "走势稳定"),
        (growth_text, pe_text, drawdown_text),
    ):
        with column:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.write(description)
    st.caption("下方可调整阈值，确认后再执行筛选。" if not intent["need_clarification"] else "以上为已识别的要求，请先澄清下方提示。")
    st.markdown("**为什么这样理解？**")
    st.caption("用户表达 → 对应指标 → 筛选条件。这里展示产品的指标映射，不代表对任何股票的事实判断。")
    for key, condition_text in zip(("growth_improvement", "valuation", "stability"),
                                   (growth_text, pe_text, drawdown_text)):
        st.write(intent.get("interpretation", {}).get(key, "映射说明暂不可用"))
        st.write("↓ " + ("待澄清，暂不执行" if intent["need_clarification"] else condition_text))
    st.caption("走势稳定使用60日最大回撤作为简化指标，不等同于波动率。手动修改阈值后，以当前确认值执行。")
    with st.expander("查看结构化条件", expanded=False):
        st.caption("原始 AI 解析结果；下方手动调整的阈值以确认区域为准。")
        st.json(intent)
    if intent["need_clarification"]:
        for conflict in intent["conflicts"]:
            st.error(conflict)
        st.warning("请修改或补充需求，再点击“解析需求”。当前不执行筛选。")
        return
    st.subheader("3. 确认筛选条件")
    st.caption("仅启用条件参与筛选；经营改善比较营收同比 > 0，PE与最大回撤比较严格小于阈值。")
    left, right = st.columns(2)
    pe_limit = left.number_input("PE 阈值（小于）", min_value=0.000001, step=1.0, key="pe_limit") if pe_status == "enabled" else None
    drawdown_limit = right.number_input("最大回撤阈值（%，小于）", min_value=0.000001, max_value=100.0, step=1.0, key="drawdown_limit") if stability_status == "enabled" else None
    confirmed = {"conditions": {"growth_improvement": growth_status == "enabled", "pe_max": pe_limit, "max_drawdown_max": drawdown_limit / 100 if drawdown_limit is not None else None},
                 "need_clarification": False, "conflicts": []}
    if "run" in st.session_state and st.session_state["run"]["intent"] != confirmed:
        st.session_state.pop("run")
        st.info("阈值已修改，请点击“确认条件并执行筛选”更新结果。")
    if st.button("确认条件并执行筛选", key="execute", type="primary"):
        st.session_state.pop("run", None)
        try:
            frame = load_dataset()
            results = screen_stocks(frame.to_dict("records"), confirmed["conditions"])
            caption = "来源：扶摇 API 本地缓存"
            meta_path = DATASET_PATH.with_suffix(".meta.json")
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    caption += f" · 构建时间：{meta['built_at']} · 财报期：{meta['report']} · K线截止：{meta['kline_end']}"
                except (ValueError, KeyError, TypeError, OSError):
                    caption += " · 缓存时间信息不可用"
            else:
                caption += " · 未提供缓存时间信息"
            run_id = st.session_state.get("run_id", 0) + 1
            st.session_state["run_id"] = run_id
            current_run = {"id": run_id, "frame": frame, "results": results,
                           "intent": confirmed, "source_caption": caption}
            previous = st.session_state.get("last_successful_run")
            if previous is not None:
                current_run["comparison"] = compare_runs(previous, current_run)
            st.session_state["run"] = current_run
            # 与展示状态分开保存，编辑阈值/请求失败不会丢失上次成功结果。
            # 只保留一个基准快照，不累积全部历史。
            st.session_state["last_successful_run"] = {
                key: value for key, value in current_run.items() if key != "comparison"
            }
        except FileNotFoundError:
            st.error("尚无股票数据缓存，请先运行数据流水线生成 data/stock_dataset.csv。")
        except (ValueError, OSError) as exc:
            st.error(f"无法执行筛选：{exc}")
    if "run" in st.session_state:
        show_results(st.session_state["run"])


if __name__ == "__main__":
    main()
