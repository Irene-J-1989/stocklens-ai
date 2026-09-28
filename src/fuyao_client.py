"""金融数据入口：扶摇真实 API 与本地缓存，不生成或补全金融事实。"""

import json
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from src.metrics import METRICS, is_valid_number


DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "data" / "stocks.json"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
BASE_URL = "https://fuyao.aicubes.cn"
SHANGHAI_TZ = timezone(timedelta(hours=8))


def _date_to_ms(value: str | date | int, *, end_of_day: bool = False) -> int:
    """日期按北京时间解释，结束日期包含全天；整数按毫秒时间戳解释。"""
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            raise ValueError("日期不存在，请使用有效的 YYYY-MM-DD 日期。") from None
    if type(value) is not date:
        raise ValueError("start/end 必须是 YYYY-MM-DD、date 对象或非负毫秒时间戳。")
    boundary = datetime.combine(value, time.min, tzinfo=SHANGHAI_TZ)
    return int(boundary.timestamp() * 1000) + (86_400_000 - 1 if end_of_day else 0)


class FuyaoAPIError(RuntimeError):
    """配置、网络、API 业务或响应格式错误；不包含密钥和原始响应。"""


class FuyaoClient:
    def __init__(self, cache_path: str | Path = DEFAULT_CACHE) -> None:
        # 固定加载项目根目录；部署环境已设置的变量优先于 .env。
        load_dotenv(ENV_FILE, override=False, encoding="utf-8-sig")
        self._api_key = os.getenv("FUYAO_API_KEY", "").strip()
        self.cache_path = Path(cache_path)

    def _get_data(self, path: str, params: dict[str, str]) -> dict:
        """复用鉴权、超时和业务错误检查，不输出密钥或原始响应。"""
        # 延迟检查密钥，确保只读本地缓存的现有页面仍可无密钥运行。
        if not self._api_key:
            raise FuyaoAPIError("缺少 FUYAO_API_KEY，请在环境变量或项目根目录 .env 中配置。")
        try:
            response = requests.get(
                f"{BASE_URL}{path}",
                params=params,
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
                1001: "缺少必填参数",
                1002: "参数格式非法",
                1003: "请求参数超出接口限制",
                2001: "API Key 缺失或无效",
                2003: "API Key 无权访问该接口",
                3001: "目标股票不在 A 股代码表中",
                5002: "上游数据源超时",
                5003: "上游数据源不可用",
            }.get(code, "服务端拒绝请求，请查询扶摇错误码说明")
            raise FuyaoAPIError(f"扶摇 API 业务失败（code={code}）：{reason}。")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise FuyaoAPIError("扶摇 API 响应格式错误：data 必须是对象。")
        return data

    def _get_items(self, path: str, params: dict[str, str]) -> list[dict]:
        """成分股与估值接口的列表响应适配。"""
        data = self._get_data(path, params)
        if not isinstance(data.get("item"), list):
            raise FuyaoAPIError("扶摇 API 响应格式错误：data.item 必须是数组。")
        return data["item"]

    def get_hs300_components(self) -> list[dict[str, str]]:
        """实时获取沪深 300 成分股，仅返回 API 的 thscode 和 name。"""
        items = self._get_items(
            "/api/a-share-index/constituents/ths-stock-list", {"thscode": "000300.SH"}
        )
        if not items:
            raise FuyaoAPIError("扶摇 API 返回空的沪深 300 成分股列表。")
        components = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict) or any(
                not isinstance(item.get(field), str) or not item[field].strip()
                for field in ("thscode", "name")
            ):
                raise FuyaoAPIError(f"扶摇 API 第 {index} 条记录缺少有效的 thscode 或 name。")
            components.append({"thscode": item["thscode"], "name": item["name"]})
        return components

    def get_valuation_snapshot(self, thscodes: str | list[str]) -> list[dict]:
        """查询估值快照，接受逗号分隔字符串或代码列表，统一返回记录列表。

        每条记录包含 thscode、name、pe_ttm。保留 API 的 null 和负值；
        无匹配数据返回空列表，未返回的股票不生成占位记录。
        """
        if isinstance(thscodes, str):
            tokens = thscodes.split(",")
        elif isinstance(thscodes, list):
            tokens = thscodes
        else:
            raise ValueError("thscodes 必须是逗号分隔的字符串或股票代码列表。")
        if not 1 <= len(tokens) <= 100:
            raise ValueError("单次估值查询需要 1～100 个股票代码。")
        if any(not isinstance(token, str) for token in tokens):
            raise ValueError("每个股票代码必须是字符串。")
        codes = [token.strip().upper() for token in tokens]
        if any(not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code) for code in codes):
            raise ValueError("股票代码格式错误，应为六位数字加 .SH、.SZ 或 .BJ。")
        codes = list(dict.fromkeys(codes))
        items = self._get_items(
            "/api/a-share/valuations/snapshot", {"thscodes": ",".join(codes)}
        )
        records = []
        seen = set()
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict) or not {"thscode", "name", "pe_ttm"} <= item.keys():
                raise FuyaoAPIError(f"估值响应第 {index} 条记录缺少 thscode、name 或 pe_ttm 字段。")
            code, name, pe_ttm = item["thscode"], item["name"], item["pe_ttm"]
            if not isinstance(code, str) or code not in codes or code in seen:
                raise FuyaoAPIError(f"估值响应第 {index} 条记录代码异常、重复或不属于请求范围。")
            if name is not None and (not isinstance(name, str) or not name.strip()):
                raise FuyaoAPIError(f"估值响应第 {index} 条记录的 name 必须是非空字符串或 null。")
            if pe_ttm is not None and not is_valid_number(pe_ttm):
                raise FuyaoAPIError(f"估值响应第 {index} 条记录的 pe_ttm 必须是有限数值或 null。")
            seen.add(code)
            records.append({"thscode": code, "name": name, "pe_ttm": pe_ttm})
        return records

    def get_financial_indicators(self, thscode: str, report: str) -> dict[str, str | None]:
        """获取指定报告期的营收同比增长率，保留 API 原始字符串或 null。

        report 为 YYYY-[1-4]，分别代表一季报、中报、三季报、年报。
        不换算单位、不补零；缺少指标与显式 null 分别处理。
        """
        if not isinstance(thscode, str) or not re.fullmatch(
            r"[0-9]{6}\.(SH|SZ|BJ)", thscode.strip().upper()
        ):
            raise ValueError("thscode 必须是单个股票代码，格式为六位数字加 .SH、.SZ 或 .BJ。")
        if not isinstance(report, str) or not re.fullmatch(r"[0-9]{4}-[1-4]", report.strip()):
            raise ValueError("report 格式必须为 YYYY-[1-4]，例如 2026-2。")
        thscode, report = thscode.strip().upper(), report.strip()
        data = self._get_data(
            "/api/a-share/financials/indicators", {"thscode": thscode, "report": report}
        )
        if data.get("thscode") != thscode or data.get("report") != report:
            raise FuyaoAPIError("财务指标响应的股票代码或报告期与请求不一致。")
        abilities = data.get("abilities")
        if not isinstance(abilities, list):
            raise FuyaoAPIError("财务指标响应格式错误：abilities 必须是数组。")
        field = "calculate_operating_income_yoy_growth_ratio"
        matches = []
        for ability in abilities:
            if not isinstance(ability, dict) or not isinstance(ability.get("indicators"), list):
                raise FuyaoAPIError("财务指标响应格式错误：指标块必须包含 indicators 数组。")
            if ability.get("ability") != "growth":
                continue
            for indicator in ability["indicators"]:
                if not isinstance(indicator, dict):
                    raise FuyaoAPIError("财务指标响应格式错误：指标项必须是对象。")
                if indicator.get("index_id") == field:
                    if "value" not in indicator:
                        raise FuyaoAPIError("营业收入同比增长率指标缺少 value 字段。")
                    matches.append(indicator["value"])
        if len(matches) != 1:
            raise FuyaoAPIError("财务指标响应缺少营业收入同比增长率指标，或该指标重复。")
        value = matches[0]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise FuyaoAPIError("营业收入同比增长率必须是非空字符串或 null。")
        return {"thscode": data["thscode"], "report": data["report"], field: value}

    def get_historical_prices(
        self, thscode: str, start: str | date | int, end: str | date | int
    ) -> list[dict[str, int | float]]:
        """获取前复权日 K 线，按日期升序返回 date_ms、close_price。

        日期包含起止日；也可直接传入毫秒时间戳。按指定日期区间取数，
        无行情返回空列表，缺失/非法收盘价明确报错，不填造或跳过。
        """
        if not isinstance(thscode, str) or not re.fullmatch(
            r"[0-9]{6}\.(SH|SZ|BJ)", thscode.strip().upper()
        ):
            raise ValueError("thscode 必须是单个股票代码，格式为六位数字加 .SH、.SZ 或 .BJ。")
        start_ms = _date_to_ms(start)
        end_ms = _date_to_ms(end, end_of_day=True)
        if start_ms > end_ms:
            raise ValueError("start 不能晚于 end。")
        items = self._get_items(
            "/api/a-share/prices/historical",
            {
                "thscode": thscode.strip().upper(), "interval": "1d",
                "start": str(start_ms), "end": str(end_ms), "adjust": "forward",
            },
        )
        records = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                raise FuyaoAPIError("历史 K 线响应格式错误：记录必须是对象。")
            timestamp, close = item.get("date_ms"), item.get("close_price")
            if type(timestamp) is not int or not start_ms <= timestamp <= end_ms:
                raise FuyaoAPIError("历史 K 线日期无效或超出请求范围。")
            if timestamp in seen:
                raise FuyaoAPIError("历史 K 线存在重复日期。")
            if not is_valid_number(close) or close <= 0:
                raise FuyaoAPIError("历史 K 线收盘价缺失或无效，必须为有限正数。")
            seen.add(timestamp)
            records.append({"date_ms": timestamp, "close_price": close})
        return sorted(records, key=lambda record: record["date_ms"])

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
