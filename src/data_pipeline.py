"""沪深300真实数据流水线；缺失/失败保留 NaN，并记录来源和错误。"""

from datetime import datetime, time, timedelta
import json
import logging
from pathlib import Path
import re
import tempfile

import pandas as pd

from src.fuyao_client import FuyaoAPIError, FuyaoClient, SHANGHAI_TZ
from src.metrics import calculate_max_drawdown, is_valid_number


LOGGER = logging.getLogger(__name__)
DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "data" / "stock_dataset.csv"
COLUMNS = ["code", "name", "revenue_yoy", "pe_ttm", "max_drawdown"]
GROWTH_FIELD = "calculate_operating_income_yoy_growth_ratio"


def _numeric(value: object) -> float:
    """只转换 API 数值，不补零；保留负增长和负 PE。"""
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            raise ValueError("指标不是有效数值。") from None
    if not is_valid_number(value):
        raise ValueError("指标缺失或不是有限数值。")
    return float(value)


def _atomic_write(path: Path, writer) -> None:
    """完整写入临时文件后替换，避免中断导致半份缓存。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        writer(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_stock_dataset(
    *, report: str | None = None, cache_path: str | Path = DEFAULT_DATASET,
    client: FuyaoClient | None = None,
) -> pd.DataFrame:
    """刷新股票池并保存五列 DataFrame，不读取旧缓存伪装为本次结果。

    默认财报期为当前已结束的最近自然季度（不保证每家公司均已披露）；
    可通过 report 显式统一指定报告期。不会回退到其他报告期。
    最大回撤使用截至本次运行日已收盘的最近60根前复权日K线。
    单项失败只留空该指标；股票池失败则抛错并保留旧缓存。
    CSV 空单元格表示缺失；同名 .meta.json 保存时间、报告期及逐项错误。
    """
    now = datetime.now(SHANGHAI_TZ)
    if report is None:
        quarter = (now.month - 1) // 3
        report = f"{now.year}-{quarter}" if quarter else f"{now.year - 1}-4"
    if not isinstance(report, str) or not re.fullmatch(r"[0-9]{4}-[1-4]", report):
        raise ValueError("report 格式必须为 YYYY-[1-4]。")
    end = now.date() if now.time() >= time(15) else now.date() - timedelta(days=1)
    cache_path = Path(cache_path)
    client = client or FuyaoClient()
    errors = []

    def record_error(code: str | None, stage: str, message: str) -> None:
        errors.append({"code": code, "stage": stage, "message": message})
        LOGGER.warning("股票 %s / %s：%s", code or "股票池", stage, message)

    try:
        components = client.get_hs300_components()
    except FuyaoAPIError:
        LOGGER.error("沪深300股票池获取失败，未覆盖现有缓存。")
        raise
    codes = [item["thscode"] for item in components]
    if not codes or len(codes) != len(set(codes)):
        raise FuyaoAPIError("股票池为空或存在重复代码，未覆盖现有缓存。")
    LOGGER.info("股票池：%d 只；报告期：%s；K线截止日期：%s", len(codes), report, end)

    # 估值接口允许批量请求，最多100只；不请求全市场，也不重复取名称。
    valuations = {}
    valuation_failed = set()
    for offset in range(0, len(codes), 100):
        batch = codes[offset:offset + 100]
        try:
            for item in client.get_valuation_snapshot(batch):
                valuations[item["thscode"]] = item["pe_ttm"]
        except FuyaoAPIError as exc:
            for code in batch:
                valuation_failed.add(code)
                record_error(code, "pe_ttm", str(exc))

    rows, windows = [], {}
    for index, component in enumerate(components, start=1):
        code = component["thscode"]
        row = {"code": code, "name": component["name"],
               "revenue_yoy": float("nan"), "pe_ttm": float("nan"), "max_drawdown": float("nan")}
        if code not in valuation_failed:
            try:
                row["pe_ttm"] = _numeric(valuations.get(code))
            except ValueError as exc:
                record_error(code, "pe_ttm", str(exc))
        try:
            financial = client.get_financial_indicators(code, report)
            row["revenue_yoy"] = _numeric(financial.get(GROWTH_FIELD))
        except (FuyaoAPIError, ValueError) as exc:
            record_error(code, "revenue_yoy", str(exc))
        try:
            for days in (120, 240, 365):
                bars = client.get_historical_prices(code, end - timedelta(days=days), end)
                if len(bars) >= 60:
                    break
            if len(bars) < 60:
                raise ValueError("近一年内不足60根日K线，不计算60日最大回撤。")
            recent = bars[-60:]
            row["max_drawdown"] = calculate_max_drawdown([bar["close_price"] for bar in recent])
            windows[code] = {"first_date_ms": recent[0]["date_ms"],
                             "last_date_ms": recent[-1]["date_ms"], "bars": 60}
        except (FuyaoAPIError, ValueError) as exc:
            record_error(code, "max_drawdown", str(exc))
        rows.append(row)
        if index % 25 == 0 or index == len(components):
            LOGGER.info("已处理 %d/%d 只，记录 %d 项缺失/错误", index, len(components), len(errors))

    frame = pd.DataFrame(rows, columns=COLUMNS)
    metadata = {"source": "fuyao", "built_at": datetime.now(SHANGHAI_TZ).isoformat(),
                "report": report, "kline_end": end.isoformat(), "adjust": "forward",
                "stock_count": len(frame), "errors": errors, "kline_windows": windows,
                "missing_counts": {column: int(frame[column].isna().sum()) for column in COLUMNS}}
    _atomic_write(cache_path, lambda path: frame.to_csv(path, index=False, encoding="utf-8-sig", na_rep=""))
    _atomic_write(cache_path.with_suffix(".meta.json"), lambda path: path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"))
    frame.attrs.update(metadata)
    LOGGER.info("已保存 %s", cache_path)
    return frame


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    dataset = build_stock_dataset()
    print(f"股票数量：{len(dataset)}")
    print(dataset.isna().sum().to_string())
