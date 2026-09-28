"""StockLens AI：解析、确认条件、读取本地真实缓存、展示规则匹配。"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.ai_parser import parse_intent
from src.explainer import explain_conditions, explain_results
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


def show_results(run: dict) -> None:
    """表格和详情始终使用同一次已确认筛选快照，避免重跑后错配。"""
    frame, results = run["frame"], run["results"]
    st.subheader("4. 规则匹配结果")
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
    st.write(explain_results([result], run["intent"]))
    st.markdown("**入选原因 / 已通过条件**")
    passed = [reason for reason in result["reasons"] if reason["passed"] is True]
    if not passed:
        st.write("没有已通过的条件。")
    for reason in passed:
        st.write(reason["message"])
    st.markdown("**失败条件**")
    if not result["failed_conditions"]:
        st.write("无，全部启用条件均匹配。")
    for key in result["failed_conditions"]:
        reason = next(item for item in result["reasons"] if item["condition"] == key)
        st.write(f"{CONDITION_LABELS[key]}：{reason['message']}")


def main() -> None:
    st.set_page_config(page_title="StockLens AI", page_icon="📊", layout="wide")
    st.title("StockLens AI")
    st.caption("自然语言选股 · 确定性筛选 · 条件解释")
    st.info("仅展示规则匹配结果，不提供买入建议或涨跌预测。意图理解使用本地规则解析。")
    st.subheader("1. 描述选股需求")
    query = st.text_area("自然语言选股需求", "经营改善、估值合理、走势稳定", key="query")
    if st.button("解析需求", key="parse", type="primary"):
        st.session_state.pop("run", None)
        intent = parse_intent(query)
        st.session_state["intent"] = intent
        st.session_state["parsed_query"] = query
        st.session_state["pe_limit"] = float(intent["conditions"].get("pe_max", 30))
        st.session_state["drawdown_limit"] = float(intent["conditions"].get("max_drawdown_max", 0.15)) * 100
    if "intent" not in st.session_state:
        return
    if query != st.session_state["parsed_query"]:
        st.session_state.pop("run", None)
        st.warning("需求已修改，请重新解析后再确认条件。")
        return
    intent = st.session_state["intent"]
    st.subheader("2. AI 解析结果")
    st.json(intent)
    st.write(explain_conditions(intent))
    if intent["need_clarification"]:
        for conflict in intent["conflicts"]:
            st.error(conflict)
        st.warning("请修改或补充需求，再点击“解析需求”。当前不执行筛选。")
        return
    st.subheader("3. 确认筛选条件")
    st.caption("经营改善：营业收入同比 > 0。PE与最大回撤均使用严格小于阈值。")
    left, right = st.columns(2)
    pe_limit = left.number_input("PE 阈值（小于）", min_value=0.000001, step=1.0, key="pe_limit")
    drawdown_limit = right.number_input("最大回撤阈值（%，小于）", min_value=0.000001, max_value=100.0, step=1.0, key="drawdown_limit")
    confirmed = {"conditions": {**intent["conditions"], "pe_max": pe_limit, "max_drawdown_max": drawdown_limit / 100},
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
            st.session_state["run"] = {"id": run_id, "frame": frame, "results": results,
                                       "intent": confirmed, "source_caption": caption}
        except FileNotFoundError:
            st.error("尚无股票数据缓存，请先运行数据流水线生成 data/stock_dataset.csv。")
        except (ValueError, OSError) as exc:
            st.error(f"无法执行筛选：{exc}")
    if "run" in st.session_state:
        show_results(st.session_state["run"])


if __name__ == "__main__":
    main()
