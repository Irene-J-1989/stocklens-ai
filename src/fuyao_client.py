"""金融数据唯一入口：当前仅读取本地缓存，不进行网络请求。"""

import json
from pathlib import Path

from src.metrics import METRICS, is_valid_number


DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "data" / "stocks.json"


class FuyaoClient:
    def __init__(self, cache_path: str | Path = DEFAULT_CACHE) -> None:
        self.cache_path = Path(cache_path)

    def fetch_stocks(self) -> list[dict]:
        """真实 API 接口预留；接入前需确认鉴权、字段和单位。"""
        raise NotImplementedError("尚未实现扶摇金融数据 API 调用，请使用本地缓存。")

    def load_snapshot(self) -> dict:
        """读取来源信息及股票记录；缺失指标保留为空，不填造数据。"""
        if not self.cache_path.exists():
            return {"source": "fuyao", "as_of": None, "stocks": []}
        try:
            snapshot = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("股票缓存不是有效的 UTF-8 JSON。") from exc
        if not isinstance(snapshot, dict) or snapshot.get("source") != "fuyao":
            raise ValueError("缓存必须声明 source 为 fuyao。")
        stocks = snapshot.get("stocks")
        if not isinstance(stocks, list):
            raise ValueError("缓存 stocks 必须是数组。")
        if stocks and (not isinstance(snapshot.get("as_of"), str) or not snapshot["as_of"].strip()):
            raise ValueError("非空缓存必须记录 as_of 数据时间。")
        records = []
        for stock in stocks:
            if not isinstance(stock, dict):
                raise ValueError("每条股票记录必须是对象。")
            for key in ("symbol", "name"):
                if not isinstance(stock.get(key), str) or not stock[key].strip():
                    raise ValueError(f"股票记录缺少有效的 {key}。")
            record = {"symbol": stock["symbol"], "name": stock["name"]}
            for field in METRICS:
                value = stock.get(field)
                if value is not None and not is_valid_number(value):
                    raise ValueError(f"指标 {field} 必须是有限数值或 null。")
                record[field] = value
            records.append(record)
        return {"source": "fuyao", "as_of": snapshot.get("as_of"), "stocks": records}
