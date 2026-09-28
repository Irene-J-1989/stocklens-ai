"""金融数据入口：扶摇真实 API 与本地缓存，不生成或补全金融事实。"""

import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from src.metrics import METRICS, is_valid_number


DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "data" / "stocks.json"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
BASE_URL = "https://fuyao.aicubes.cn"


class FuyaoAPIError(RuntimeError):
    """配置、网络、API 业务或响应格式错误；不包含密钥和原始响应。"""


class FuyaoClient:
    def __init__(self, cache_path: str | Path = DEFAULT_CACHE) -> None:
        # 固定加载项目根目录；部署环境已设置的变量优先于 .env。
        load_dotenv(ENV_FILE, override=False, encoding="utf-8-sig")
        self._api_key = os.getenv("FUYAO_API_KEY", "").strip()
        self.cache_path = Path(cache_path)

    def get_hs300_components(self) -> list[dict[str, str]]:
        """实时获取沪深 300 成分股，仅返回 API 的 thscode 和 name。"""
        # 延迟检查密钥，确保只读本地缓存的现有页面仍可无密钥运行。
        if not self._api_key:
            raise FuyaoAPIError("缺少 FUYAO_API_KEY，请在环境变量或项目根目录 .env 中配置。")
        try:
            response = requests.get(
                f"{BASE_URL}/api/a-share-index/constituents/ths-stock-list",
                params={"thscode": "000300.SH"},
                headers={"X-api-key": self._api_key, "Accept": "application/json"},
                timeout=(10, 30),
                # 不跟随重定向，避免将自定义鉴权头转发到其他地址。
                allow_redirects=False,
            )
        except requests.Timeout:
            raise FuyaoAPIError("扶摇 API 请求超时，请稍后重试。") from None
        except requests.RequestException:
            raise FuyaoAPIError("扶摇 API 请求失败，请检查网络、代理及 TLS 配置。") from None

        with response:
            if response.status_code != 200:
                raise FuyaoAPIError(f"扶摇 API 返回 HTTP {response.status_code}，请检查服务、鉴权或访问频率。")
            try:
                payload = response.json()
            except ValueError:
                raise FuyaoAPIError("扶摇 API 返回非 JSON 响应。") from None
        if not isinstance(payload, dict) or type(payload.get("code")) is not int:
            raise FuyaoAPIError("扶摇 API 响应格式错误：缺少整数 code。")
        code = payload["code"]
        if code != 0:
            reason = {
                2001: "API Key 缺失或无效",
                2003: "API Key 无权访问该接口",
            }.get(code, "服务端拒绝请求，请查询扶摇错误码说明")
            raise FuyaoAPIError(f"扶摇 API 业务失败（code={code}）：{reason}。")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            raise FuyaoAPIError("扶摇 API 响应格式错误：data.item 必须是数组。")
        if not data["item"]:
            raise FuyaoAPIError("扶摇 API 返回空的沪深 300 成分股列表。")
        components = []
        for index, item in enumerate(data["item"], start=1):
            if not isinstance(item, dict) or any(
                not isinstance(item.get(field), str) or not item[field].strip()
                for field in ("thscode", "name")
            ):
                raise FuyaoAPIError(f"扶摇 API 第 {index} 条记录缺少有效的 thscode 或 name。")
            components.append({"thscode": item["thscode"], "name": item["name"]})
        return components

    def fetch_stocks(self) -> list[dict]:
        """筛选指标接口预留；成分股列表不包含筛选所需的金融指标。"""
        raise NotImplementedError("尚未实现筛选指标 API 调用，请使用本地缓存。")

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
