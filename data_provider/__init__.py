# -*- coding: utf-8 -*-
"""
===================================
数据源策略层 - 包初始化
===================================

本包实现策略模式管理多个数据源，实现：
1. 统一的数据获取接口
2. 自动故障切换
3. 防封禁流控策略

数据源优先级（动态调整）：
【默认配置】
1. CodebuddyFetcher (Priority -2) - 🔥 最高优先级，免费无配额限制
2. TushareFetcher (Priority -1) - 配置 Token 后提升
3. EfinanceFetcher (Priority 0) - 东方财富爬虫
4. AkshareFetcher (Priority 1) - 来自 akshare 库
5. PytdxFetcher (Priority 2) - 来自 pytdx 库（通达信）
6. BaostockFetcher (Priority 3) - 来自 baostock 库
7. YfinanceFetcher (Priority 4) - 来自 yfinance 库

提示：优先级数字越小越优先，同优先级按初始化顺序排列
"""

from .base import BaseFetcher, DataFetcherManager
from .codebuddy_fetcher import CodebuddyFetcher
from .efinance_fetcher import EfinanceFetcher
from .akshare_fetcher import AkshareFetcher, is_hk_stock_code
from .tushare_fetcher import TushareFetcher
from .pytdx_fetcher import PytdxFetcher
from .baostock_fetcher import BaostockFetcher
from .yfinance_fetcher import YfinanceFetcher
from .us_index_mapping import is_us_index_code, is_us_stock_code, get_us_index_yf_symbol, US_INDEX_MAPPING

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'CodebuddyFetcher',
    'EfinanceFetcher',
    'AkshareFetcher',
    'TushareFetcher',
    'PytdxFetcher',
    'BaostockFetcher',
    'YfinanceFetcher',
    'is_us_index_code',
    'is_us_stock_code',
    'is_hk_stock_code',
    'get_us_index_yf_symbol',
    'US_INDEX_MAPPING',
]
