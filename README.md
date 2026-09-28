# StockLens AI

Python + Streamlit 的「自然语言智能选股与策略解释器」MVP。

输入偏好 → 意图解析生成 JSON → 确定性引擎筛选 API / 缓存数据 → 展示结果和解释。

当前规则解析器和模板解释器可运行，尚未接入 LLM 或真实扶摇 API。
缓存初始为空，不提供虚构股票。配置 API 密钥不会触发网络调用。

## 本地运行

建议使用 Python 3.11 或更新版本，在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

浏览器访问终端显示的地址（默认 http://localhost:8501）。
输入 `经营改善、估值合理、走势相对稳定` 后点击「解析并筛选」。
空缓存时仍可查看 JSON 和策略解释，页面会提示没有可筛选数据。
当前仅支持上述三个短语任意组合，以逗号或顿号分隔；未知、否定表达会报错。

## 目录与接口

```text
stocklens-ai/
├── app.py                  # Streamlit 页面
├── requirements.txt
├── README.md
├── .env.example            # 接入配置占位，当前不读取
├── src/
│   ├── __init__.py
│   ├── fuyao_client.py      # FuyaoClient.load_snapshot / fetch_stocks
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

当前演示映射：经营改善 = 营收、净利润同比增长率均大于 0；估值合理 =
0 < PE TTM ≤ 30；走势相对稳定 = 0 ≤ 20 日波动率 ≤ 3%。
这些是简化的产品规则，不代表完整经营分析。

## 本地缓存约定

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

测试只使用隔离的合成数值，不包含股票名称或行情，也不会写入产品缓存。
