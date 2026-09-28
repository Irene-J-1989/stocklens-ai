# StockLens AI

Python + Streamlit 的「自然语言智能选股与策略解释器」MVP。

输入偏好 → 意图解析生成 JSON → 确定性引擎筛选 API / 缓存数据 → 展示结果和解释。

意图解析优先通过 OpenAI SDK 调用 DeepSeek（`deepseek-chat`）；未配置密钥或调用失败时自动回退到规则解析。
解释器仍使用确定性模板，只引用已有筛选数据。
客户端已接入扶摇股票池、估值、财务及日 K 线 API，批量流水线可生成真实数据缓存。
Streamlit 页面读取 `data/stock_dataset.csv`，展示可确认的条件和逐只股票的匹配详情。

## 本地运行

建议使用 Python 3.11 或更新版本，在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

浏览器访问终端显示的地址（默认 http://localhost:8501）。
输入 `经营改善、估值合理、走势稳定` 后点击「解析需求」，查看条件、澄清标记和冲突信息。
无冲突且条件完整时，可修改 PE 上限和最大回撤上限（百分比），再点击「确认条件并执行筛选」。
表格展示全部股票的指标和是否入选，点击行或使用股票选择框查看通过原因及失败条件。
修改需求或阈值后旧结果会隐藏，需重新执行。页面只展示规则匹配，不输出买入建议或涨跌预测。
缓存缺失时会提示先运行流水线；不会自动联网取数。模糊、否定或冲突需求会要求澄清。

## 目录与接口

```text
stocklens-ai/
├── app.py                  # Streamlit 页面
├── requirements.txt
├── README.md
├── .env.example            # 密钥模板；复制为 .env 后填写
├── src/
│   ├── __init__.py
│   ├── fuyao_client.py      # FuyaoClient.load_snapshot / fetch_stocks
│   ├── data_pipeline.py     # build_stock_dataset 批量取数与 CSV 缓存
│   ├── ai_parser.py         # parse_intent / validate_criteria
│   ├── screener.py          # screen_stocks
│   ├── metrics.py           # 指标约定及数值校验
│   └── explainer.py         # explain_conditions / explain_results
├── data/
│   └── stocks.json          # 空缓存，未来导入 API 数据
└── tests/
    └── test_core.py
```

## 金融数据与 AI 边界

- LLM 只负责理解意图和解释，不得生成股票名称、价格、PE 或其他金融事实。
- 金融事实只能由扶摇 API 或其本地缓存提供。结果表直接使用缓存中的记录。
- 未来 LLM 输出必须通过 `validate_criteria`，仅接受白名单指标、运算符和数值阈值。
- 策略阈值属于筛选参数，不是金融事实；当前示例阈值不代表行业通用估值标准。
- 引擎使用 AND 比较，缺失指标不补零，非法数值拒绝加载；解释器不推测缺失事实。

当前页面映射：经营改善 = 营收同比增长率大于 0；估值合理 = PE TTM < 30；
走势稳定 = 最近60根前复权日K线的最大回撤 < 15%。上限可由用户确认修改。
这些是简化的产品规则，不代表完整经营分析。

## 旧版 JSON 缓存约定（兼容接口）

`data/stocks.json` 顶层字段为 `source`（固定 `fuyao`）、`as_of`（数据时间）和 `stocks`（记录数组）。
非空缓存必须填写数据时间；来源标签仅为元数据，不会自动验证数据的真实出处。
只导入实际 API 响应转换的数据，不手填或让 LLM 生成金融事实。

每条记录字段如下（内部模型，尚未确认扶摇字段映射）：

| 字段 | 含义 / 单位 |
| --- | --- |
| symbol | 股票代码，字符串，保留前导零 |
| name | API 返回的股票名称 |
| revenue_growth_yoy | 营收同比增长率，百分数，5 表示 5% |
| net_profit_growth_yoy | 净利润同比增长率，百分数 |
| pe_ttm | 滚动市盈率，倍 |
| volatility_20d | 最近 20 个交易日日收益率的非年化标准差，百分数 |

指标可为 `null` 或缺失。接入时需确认报告期、复权方式、波动率计算约定和单位；
若 API 不提供对应口径，应从 API 历史数据确定性计算，不能由模型推断。
`fetch_stocks()` 当前明确抛出 `NotImplementedError`，不猜测端点或鉴权方式。
缓存当前不会自动刷新；数据时间会在结果页面显示。

## 验证

```powershell
python -m unittest discover -s tests -v
```

核心规则测试不联网；API 集成测试需要 `.env` 中的有效 `FUYAO_API_KEY`。
全量流水线测试会真实读取沪深300数据并更新 CSV，可能需要数分钟。

## 批量数据流水线

```powershell
.\.venv\Scripts\python.exe -X utf8 -m src.data_pipeline
.\.venv\Scripts\python.exe -X utf8 tests/test_pipeline.py
```

也可显式指定统一财报期：

```python
from src.data_pipeline import build_stock_dataset
from src.screener import screen_stocks

df = build_stock_dataset(report="2026-2")
results = screen_stocks(df.to_dict("records"), {
    "growth_improvement": True, "pe_max": 30, "max_drawdown_max": 0.15,
})
```

输出 `data/stock_dataset.csv`，字段固定为 `code`、`name`、`revenue_yoy`、
`pe_ttm`、`max_drawdown`。营收同比来自 API 原值转数值，PE 单位为倍，
最大回撤为最近60根已收盘前复权日K线计算的比例（0.15 表示15%）。
默认财报期是当前已结束的最近自然季度，可能尚未披露；不会自动换用其他报告期。

每次调用都会刷新数据。单项失败保留该股票，只有失败的指标留为 NaN；
CSV 中保存为空单元格，不补零、不生成占位金融值。股票池获取失败会抛错并保留旧缓存。
`data/stock_dataset.meta.json` 记录来源、构建时间、报告期、实际K线窗口、缺失数量和逐项错误。
缓存文件均受 Git 忽略规则保护。`tests/test_pipeline.py` 还通过注入请求异常检验缺失处理，
该分支使用临时目录，不向正式缓存写入测试故障数据。

## DeepSeek 意图解析

在项目根目录 `.env` 中设置 `LLM_API_KEY`，无需修改扶摇密钥。
请求固定发送至 `https://api.deepseek.com`，模型为 `deepseek-chat`。
只发送用户需求和策略约束，不发送股票数据集、缓存或扶摇 API Key。
模型只能返回 `conditions`、`need_clarification`、`conflicts`；字段、类型、阈值、完整性和重复 JSON 键均会校验。
模型的自由文本冲突内容不会透传，避免夹带名称、价格或预测。

缺少密钥、SDK/API 请求失败、空响应、截断或非法 JSON 时自动调用 `parse_rule_intent()`。
部分或模糊需求允许 `conditions` 不完整，但必须要求澄清；未澄清的结果不会执行筛选。
解析器不会生成股票或行情，只产出待用户确认的规则阈值。

```powershell
.\.venv\Scripts\python.exe -X utf8 tests/test_ai_parser_llm.py
```

此测试隔离模型响应，覆盖正常、模糊、冲突需求、缺密钥、调用失败和 JSON 校验失败；不会消耗 API 额度。
