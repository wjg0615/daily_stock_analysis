# -*- coding: utf-8 -*-
"""
===================================
CodebuddyFetcher - 最高优先级数据源 (Priority -2)
===================================

数据来源：金融数据 API

API 说明：
- 支持：A股日线、指数、ETF、港股、美股等 209 个接口

优先级：-2（最高，优于 Tushare 的 -1）
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import pandas as pd
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import (
    BaseFetcher,
    DataFetchError,
    RateLimitError,
    STANDARD_COLUMNS,
    normalize_stock_code,
    is_bse_code,
)
from .us_index_mapping import is_us_stock_code, is_us_index_code
from .realtime_types import ChipDistribution, safe_float

logger = logging.getLogger(__name__)

# CodeBuddy API 端点
CODEBUDDY_API_URL = "https://www.codebuddy.cn/v2/tool/financedata"

# 请求超时（秒）
REQUEST_TIMEOUT = 30


def _is_us_code(stock_code: str) -> bool:
    """判断代码是否为美股"""
    code = stock_code.strip().upper()
    return is_us_index_code(code) or is_us_stock_code(code)


def _is_hk_code(stock_code: str) -> bool:
    """判断代码是否为港股"""
    normalized = stock_code.strip().upper()
    if normalized.startswith("HK"):
        return True
    if normalized.isdigit() and len(normalized) == 5:
        return True
    return False


def _get_ts_code(stock_code: str) -> str:
    """
    将股票代码转换为 Tushare 格式（带交易所后缀）

    Args:
        stock_code: 原始股票代码，如 '600519', '000001', 'AAPL'

    Returns:
        Tushare 格式代码，如 '600519.SH', '000001.SZ', 'AAPL'
    """
    code = normalize_stock_code(stock_code)
    
    # 美股直接返回大写代码
    if _is_us_code(code):
        return code.upper()
    
    # 港股
    if _is_hk_code(code):
        if code.upper().startswith("HK"):
            return code.upper()
        return f"HK{code.zfill(5)}"
    
    # A 股判断交易所
    if not code.isdigit() or len(code) != 6:
        return code
    
    # 上海交易所：60xxxx, 68xxxx, 51xxxx, 52xxxx, 56xxxx, 58xxxx
    if code.startswith(('60', '68', '51', '52', '56', '58')):
        return f"{code}.SH"
    
    # 深圳交易所：00xxxx, 30xxxx, 15xxxx, 16xxxx, 18xxxx
    if code.startswith(('00', '30', '15', '16', '18')):
        return f"{code}.SZ"
    
    # 北交所：8xxxxx, 4xxxxx, 92xxxx
    if code.startswith(('8', '4')) or code.startswith('92'):
        return f"{code}.BJ"
    
    # 默认深圳
    return f"{code}.SZ"


class CodebuddyFetcher(BaseFetcher):
    """
    CodeBuddy 金融数据源实现

    优先级：-2（最高）
    数据来源：CodeBuddy API（Tushare 同源数据）

    优势：
    - 无需 Token
    - 无配额限制
    - 数据质量高
    - 支持 A 股、港股、美股

    限制：
    - 实时行情接口不支持 HTTP（仅 SDK）
    - 复权行情接口不支持 HTTP（仅 SDK）
    """

    name = "CodebuddyFetcher"
    priority = -2  # 最高优先级

    def __init__(self):
        """初始化 CodebuddyFetcher"""
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        logger.info("CodebuddyFetcher 初始化成功 (Priority -2)")

    def is_available(self) -> bool:
        """检查数据源是否可用"""
        return True

    def _call_api(
        self,
        api_name: str,
        params: Dict[str, Any],
        fields: str = ""
    ) -> Dict[str, Any]:
        """
        调用 CodeBuddy API

        Args:
            api_name: 接口名称，如 'daily', 'index_daily'
            params: 接口参数
            fields: 返回字段（空则返回全部）

        Returns:
            API 响应数据

        Raises:
            DataFetchError: API 调用失败
        """
        payload = {
            "api_name": api_name,
            "params": params,
            "fields": fields
        }

        try:
            resp = self._session.post(
                CODEBUDDY_API_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                error_msg = result.get("msg", "Unknown error")
                raise DataFetchError(f"CodeBuddy API error: {error_msg}")

            return result.get("data", {})

        except requests.exceptions.Timeout:
            raise DataFetchError(f"CodeBuddy API timeout after {REQUEST_TIMEOUT}s")
        except requests.exceptions.RequestException as e:
            raise DataFetchError(f"CodeBuddy API request failed: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(DataFetchError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        从 CodeBuddy 获取原始数据

        Args:
            stock_code: 股票代码（纯数字格式，如 '600519'）
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期，格式 'YYYY-MM-DD'

        Returns:
            原始数据 DataFrame
        """
        # 格式化日期（YYYYMMDD）
        start_fmt = start_date.replace("-", "")
        end_fmt = end_date.replace("-", "")

        # 转换为 Tushare 格式代码
        ts_code = _get_ts_code(stock_code)

        # 美股使用美股接口
        if _is_us_code(stock_code):
            return self._fetch_us_data(ts_code, start_fmt, end_fmt)

        # 港股使用港股接口
        if _is_hk_code(stock_code):
            return self._fetch_hk_data(ts_code, start_fmt, end_fmt)

        # A 股日线
        return self._fetch_cn_data(ts_code, start_fmt, end_fmt)

    def _fetch_cn_data(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取 A 股日线数据"""
        logger.info(f"[API调用] CodeBuddy daily: ts_code={ts_code}, "
                   f"start_date={start_date}, end_date={end_date}")

        data = self._call_api(
            api_name="daily",
            params={
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date
            }
        )

        fields = data.get("fields", [])
        items = data.get("items", [])

        if not items:
            raise DataFetchError(f"CodeBuddy: 未获取到 {ts_code} 的数据")

        df = pd.DataFrame(items, columns=fields)
        logger.info(f"[CodebuddyFetcher] {ts_code} 获取成功: rows={len(df)}")
        return df

    def _fetch_us_data(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取美股日线数据"""
        logger.info(f"[API调用] CodeBuddy us_daily: ts_code={ts_code}, "
                   f"start_date={start_date}, end_date={end_date}")

        data = self._call_api(
            api_name="us_daily",
            params={
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date
            }
        )

        fields = data.get("fields", [])
        items = data.get("items", [])

        if not items:
            raise DataFetchError(f"CodeBuddy: 未获取到美股 {ts_code} 的数据")

        df = pd.DataFrame(items, columns=fields)
        logger.info(f"[CodebuddyFetcher] 美股 {ts_code} 获取成功: rows={len(df)}")
        return df

    def _fetch_hk_data(
        self,
        ts_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取港股日线数据"""
        logger.info(f"[API调用] CodeBuddy hk_daily: ts_code={ts_code}, "
                   f"start_date={start_date}, end_date={end_date}")

        data = self._call_api(
            api_name="hk_daily",
            params={
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date
            }
        )

        fields = data.get("fields", [])
        items = data.get("items", [])

        if not items:
            raise DataFetchError(f"CodeBuddy: 未获取到港股 {ts_code} 的数据")

        df = pd.DataFrame(items, columns=fields)
        logger.info(f"[CodebuddyFetcher] 港股 {ts_code} 获取成功: rows={len(df)}")
        return df

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化 CodeBuddy 数据

        CodeBuddy/Tushare 返回的列名：
        ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount

        标准列名：
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()

        # 列名映射
        column_mapping = {
            'trade_date': 'date',
            'vol': 'volume',
            'ts_code': 'code',
        }

        df = df.rename(columns=column_mapping)

        # 确保必要列存在
        required_cols = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        for col in required_cols:
            if col not in df.columns:
                if col in ['open', 'high', 'low']:
                    df[col] = df.get('close', 0)
                elif col in ['volume', 'amount']:
                    df[col] = 0
                elif col == 'pct_chg':
                    df[col] = 0

        # 只保留标准列
        df = df[[col for col in required_cols if col in df.columns]]

        return df

    # ============================================
    # 筹码分布数据
    # ============================================

    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        获取筹码分布数据

        使用 CodeBuddy API 的 cyq_perf 接口获取筹码成本和胜率数据。

        Args:
            stock_code: 股票代码（纯数字格式，如 '600519'）

        Returns:
            ChipDistribution 对象，获取失败返回 None
        """
        # 美股/港股没有筹码分布数据
        if _is_us_code(stock_code) or _is_hk_code(stock_code):
            logger.debug(f"[CodebuddyFetcher] {stock_code} 是美股/港股，无筹码分布数据")
            return None

        # ETF/指数没有筹码分布数据
        code = normalize_stock_code(stock_code)
        if code.startswith(('51', '52', '56', '58', '15', '16', '18')):
            logger.debug(f"[CodebuddyFetcher] {stock_code} 是 ETF，无筹码分布数据")
            return None

        ts_code = _get_ts_code(stock_code)

        try:
            logger.info(f"[API调用] CodeBuddy cyq_perf: ts_code={ts_code}")

            data = self._call_api(
                api_name="cyq_perf",
                params={"ts_code": ts_code}
            )

            fields = data.get("fields", [])
            items = data.get("items", [])

            if not items:
                logger.warning(f"[CodebuddyFetcher] {ts_code} 无筹码分布数据")
                return None

            # 日期校验：过滤出最近 30 天的数据，避免使用过期数据误导分析
            MAX_CHIP_DATA_AGE_DAYS = 30
            cutoff_date = datetime.now() - timedelta(days=MAX_CHIP_DATA_AGE_DAYS)

            # 解析所有数据并过滤
            recent_items = []
            for item in items:
                field_map = dict(zip(fields, item))
                trade_date_str = str(field_map.get("trade_date", ""))
                try:
                    # trade_date 格式通常是 YYYYMMDD
                    if len(trade_date_str) == 8:
                        trade_date = datetime.strptime(trade_date_str, "%Y%m%d")
                        if trade_date >= cutoff_date:
                            recent_items.append((trade_date, item))
                except ValueError:
                    continue

            if not recent_items:
                # 尝试获取最新数据日期用于日志
                latest_date_str = ""
                if items:
                    field_map = dict(zip(fields, items[-1]))
                    latest_date_str = str(field_map.get("trade_date", ""))
                logger.warning(f"[CodebuddyFetcher] {ts_code} 无最近 {MAX_CHIP_DATA_AGE_DAYS} 天筹码数据，"
                              f"最新数据日期: {latest_date_str}，放弃使用过期数据")
                return None

            # 按日期排序取最新一条
            recent_items.sort(key=lambda x: x[0], ascending=True)
            latest = recent_items[-1][1]
            field_map = dict(zip(fields, latest))

            # 解析字段
            weight_avg = safe_float(field_map.get("weight_avg"), 0.0)
            winner_rate = safe_float(field_map.get("winner_rate"), 0.0)
            cost_5pct = safe_float(field_map.get("cost_5pct"), 0.0)
            cost_95pct = safe_float(field_map.get("cost_95pct"), 0.0)
            cost_15pct = safe_float(field_map.get("cost_15pct"), 0.0)
            cost_85pct = safe_float(field_map.get("cost_85pct"), 0.0)
            trade_date = str(field_map.get("trade_date", ""))

            # 计算集中度
            # concentration = (cost_95pct - cost_5pct) / (cost_95pct + cost_5pct) * 2
            # 或者用 (cost_85pct - cost_15pct) / weight_avg
            if weight_avg > 0 and cost_85pct > 0 and cost_15pct > 0:
                concentration_90 = (cost_95pct - cost_5pct) / weight_avg if weight_avg > 0 else 0.0
                concentration_70 = (cost_85pct - cost_15pct) / weight_avg if weight_avg > 0 else 0.0
            else:
                concentration_90 = 0.0
                concentration_70 = 0.0

            chip = ChipDistribution(
                code=stock_code,
                date=trade_date,
                source="codebuddy",
                profit_ratio=winner_rate / 100.0 if winner_rate > 1 else winner_rate,
                avg_cost=weight_avg,
                cost_90_low=cost_5pct,
                cost_90_high=cost_95pct,
                concentration_90=concentration_90,
                cost_70_low=cost_15pct,
                cost_70_high=cost_85pct,
                concentration_70=concentration_70,
            )

            logger.info(f"[CodebuddyFetcher] {ts_code} 筹码分布获取成功: "
                       f"获利比例={winner_rate:.1f}%, 平均成本={weight_avg:.2f}")

            return chip

        except Exception as e:
            logger.warning(f"[CodebuddyFetcher] {ts_code} 筹码分布获取失败: {e}")
            return None
