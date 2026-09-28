"""StockLens AI 的 Streamlit 入口。"""

import streamlit as st

from src.ai_parser import parse_intent
from src.explainer import explain_conditions, explain_results
from src.fuyao_client import FuyaoClient
from src.screener import screen_stocks


def main() -> None:
    st.set_page_config(page_title="StockLens AI", page_icon="📊", layout="wide")
    st.title("StockLens AI")
    st.caption("自然语言智能选股与策略解释器 · MVP")
    st.info("当前使用本地规则解析和本地缓存，尚未接入 LLM 或扶摇 API。")
    with st.form("screening"):
        query = st.text_area("描述筛选偏好", "经营改善、估值合理、走势相对稳定")
        submitted = st.form_submit_button("解析并筛选")
    if not submitted:
        return
    try:
        criteria = parse_intent(query)
        st.subheader("结构化筛选条件")
        st.json(criteria)
        st.write(explain_conditions(criteria))
        snapshot = FuyaoClient().load_snapshot()
        if not snapshot["stocks"]:
            st.warning("本地缓存为空，请先导入来自扶摇金融数据 API 的数据。当前没有可供筛选的股票。")
            return
        results = screen_stocks(snapshot["stocks"], criteria)
        st.caption(f"数据来源：{snapshot['source']} · 数据时间：{snapshot['as_of']}")
        st.subheader("筛选结果")
        st.write(explain_results(results, criteria))
        if results:
            st.dataframe(results, use_container_width=True)
    except (ValueError, OSError) as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
