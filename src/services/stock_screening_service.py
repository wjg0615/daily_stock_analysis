# -*- coding: utf-8 -*-
"""
===================================
股票筛选服务
===================================

实现两阶段筛选：
1. 初步筛选：涨跌幅、量比、换手率、流通市值、排除新股
2. 策略过滤：均线排列、乖离率
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd

from data_provider.realtime_types import safe_float

logger = logging.getLogger(__name__)


# 文件缓存路径
_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache"
_CACHE_FILE = _CACHE_DIR / "realtime_quote_cache.json"
_CACHE_TTL = 1200  # 20分钟

# 筛选结果缓存
_SCREENING_CACHE_FILE = _CACHE_DIR / "screening_result_cache.json"
_SCREENING_CACHE_TTL = 7200  # 2小时


@dataclass
class ScreeningCriteria:
    """筛选条件"""
    change_pct_min: float = 3.0
    change_pct_max: float = 5.0
    volume_ratio_min: float = 1.0
    volume_ratio_max: float = 5.0
    turnover_rate_min: float = 3.0
    turnover_rate_max: float = 10.0
    circ_mv_min: float = 50e8    # 50亿
    circ_mv_max: float = 200e8   # 200亿
    exclude_new_stock_days: int = 5  # 排除上市5日内新股


@dataclass
class StrategyFilter:
    """策略过滤条件"""
    require_ma_bullish: bool = True  # MA5 > MA10 > MA20
    bias_threshold: float = 5.0      # 乖离率阈值
    require_macd_positive: bool = True  # MACD > 0 或 DIF > DEA
    require_volume_up: bool = True      # 5日均量 > 20日均量
    require_ma60_up: bool = True        # MA60 方向向上


@dataclass
class ScreenedStock:
    """筛选结果"""
    code: str
    name: str
    change_pct: float
    volume_ratio: float
    turnover_rate: float
    circ_mv: float
    price: float
    ma_status: Optional[str] = None
    bias_ma5: Optional[float] = None
    macd_status: Optional[str] = None
    volume_status: Optional[str] = None
    ma60_status: Optional[str] = None
    passed_strategy: bool = False


class StockScreeningService:
    """股票筛选服务"""
    
    BJ_PREFIX = ('8', '4')       # 北交所代码前缀
    CY_PREFIX = ('300',)         # 创业板代码前缀
    
    def __init__(self):
        pass
    
    def screen_stocks(
        self,
        criteria: Optional[ScreeningCriteria] = None,
        strategy: Optional[StrategyFilter] = None,
        apply_strategy: bool = True,
        use_cache: bool = True
    ) -> List[ScreenedStock]:
        """
        执行股票筛选
        
        Args:
            criteria: 初步筛选条件
            strategy: 策略过滤条件
            apply_strategy: 是否应用策略过滤
            use_cache: 是否使用筛选结果缓存
            
        Returns:
            筛选结果列表
        """
        criteria = criteria or ScreeningCriteria()
        strategy = strategy or StrategyFilter()
        
        # 尝试从缓存读取（仅使用默认条件时）
        if use_cache and criteria == ScreeningCriteria() and strategy == StrategyFilter():
            cached = self._load_screening_cache(apply_strategy)
            if cached:
                logger.info(f"[筛选] 使用筛选结果缓存，共 {len(cached)} 只股票")
                return cached
        
        # 第一阶段：初步筛选
        primary_results = self._primary_screening(criteria)
        logger.info(f"[筛选] 初步筛选完成，共 {len(primary_results)} 只股票")
        
        if not apply_strategy or not primary_results:
            # 如果不应用策略，标记所有股票为通过
            if not apply_strategy:
                for stock in primary_results:
                    stock.passed_strategy = True
            return primary_results
        
        # 第二阶段：策略过滤
        final_results = self._strategy_filter(primary_results, strategy)
        logger.info(f"[筛选] 策略过滤完成，共 {len(final_results)} 只股票通过")
        
        # 保存到缓存（仅使用默认条件时）
        if use_cache and criteria == ScreeningCriteria() and strategy == StrategyFilter():
            self._save_screening_cache(final_results, apply_strategy)
        
        return final_results
    
    def _load_screening_cache(self, apply_strategy: bool) -> Optional[List[ScreenedStock]]:
        """加载筛选结果缓存"""
        if not _SCREENING_CACHE_FILE.exists():
            return None
        
        try:
            with open(_SCREENING_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            cache_time = cache_data.get('timestamp', 0)
            cache_age = int(time.time() - cache_time)
            
            # 检查缓存是否过期
            if cache_age >= _SCREENING_CACHE_TTL:
                logger.info(f"[筛选] 筛选结果缓存已过期，年龄 {cache_age}s")
                return None
            
            # 检查缓存条件是否匹配
            if cache_data.get('apply_strategy') != apply_strategy:
                return None
            
            # 反序列化结果
            results = []
            for item in cache_data.get('results', []):
                results.append(ScreenedStock(
                    code=item['code'],
                    name=item['name'],
                    change_pct=item['change_pct'],
                    volume_ratio=item['volume_ratio'],
                    turnover_rate=item['turnover_rate'],
                    circ_mv=item['circ_mv'],
                    price=item['price'],
                    ma_status=item.get('ma_status'),
                    bias_ma5=item.get('bias_ma5'),
                    macd_status=item.get('macd_status'),
                    volume_status=item.get('volume_status'),
                    ma60_status=item.get('ma60_status'),
                    passed_strategy=item.get('passed_strategy', True)
                ))
            
            return results
            
        except Exception as e:
            logger.warning(f"[筛选] 读取筛选结果缓存失败: {e}")
            return None
    
    def _save_screening_cache(self, results: List[ScreenedStock], apply_strategy: bool) -> None:
        """保存筛选结果到缓存"""
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            
            cache_data = {
                'timestamp': time.time(),
                'apply_strategy': apply_strategy,
                'results': [
                    {
                        'code': s.code,
                        'name': s.name,
                        'change_pct': s.change_pct,
                        'volume_ratio': s.volume_ratio,
                        'turnover_rate': s.turnover_rate,
                        'circ_mv': s.circ_mv,
                        'price': s.price,
                        'ma_status': s.ma_status,
                        'bias_ma5': s.bias_ma5,
                        'macd_status': s.macd_status,
                        'volume_status': s.volume_status,
                        'ma60_status': s.ma60_status,
                        'passed_strategy': s.passed_strategy
                    }
                    for s in results
                ]
            }
            
            with open(_SCREENING_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[筛选] 筛选结果已缓存，共 {len(results)} 只股票")
            
        except Exception as e:
            logger.warning(f"[筛选] 保存筛选结果缓存失败: {e}")
    
    def _get_cached_realtime_data(self) -> Optional[pd.DataFrame]:
        """
        获取缓存的实时行情数据
        
        使用文件缓存，跨进程有效
        """
        import akshare as ak
        
        current_time = time.time()
        
        # 检查文件缓存
        if _CACHE_FILE.exists():
            try:
                with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                cache_time = cache_data.get('timestamp', 0)
                cache_age = int(current_time - cache_time)
                
                if cache_age < _CACHE_TTL and cache_data.get('data'):
                    logger.info(f"[筛选] 使用文件缓存，缓存年龄 {cache_age}s")
                    df = pd.DataFrame(cache_data['data'])
                    return df
            except Exception as e:
                logger.warning(f"[筛选] 读取缓存文件失败: {e}")
        
        # 缓存过期或不存在，重新获取
        logger.info("[筛选] 缓存过期或不存在，重新获取全市场实时行情...")
        try:
            df = ak.stock_zh_a_spot_em()
            logger.info(f"[筛选] 获取成功，共 {len(df)} 只股票")
            
            # 保存到文件缓存
            try:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_data = {
                    'timestamp': current_time,
                    'data': df.to_dict(orient='records')
                }
                with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False)
                logger.info(f"[筛选] 缓存已保存到 {_CACHE_FILE}")
            except Exception as e:
                logger.warning(f"[筛选] 保存缓存文件失败: {e}")
            
            return df
        except Exception as e:
            logger.error(f"[筛选] 获取实时行情失败: {e}")
            # 如果有旧缓存，降级使用
            if _CACHE_FILE.exists():
                try:
                    with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    logger.warning("[筛选] 降级使用旧缓存数据")
                    df = pd.DataFrame(cache_data.get('data', []))
                    return df
                except Exception:
                    pass
            return None
    
    def _primary_screening(self, criteria: ScreeningCriteria) -> List[ScreenedStock]:
        """初步筛选：涨跌幅、量比、换手率、流通市值"""
        
        df = self._get_cached_realtime_data()
        
        if df is None or df.empty:
            logger.warning("[筛选] 获取实时行情失败")
            return []
        
        results = []
        
        for _, row in df.iterrows():
            code = str(row.get('代码', ''))
            name = str(row.get('名称', ''))
            
            # 排除北交所、创业板
            if code.startswith(self.BJ_PREFIX):
                continue
            if code.startswith(self.CY_PREFIX):
                continue
            
            # 解析数值
            change_pct = safe_float(row.get('涨跌幅'))
            volume_ratio = safe_float(row.get('量比'))
            turnover_rate = safe_float(row.get('换手率'))
            circ_mv = safe_float(row.get('流通市值'))
            price = safe_float(row.get('最新价'))
            
            # 数据完整性检查
            if None in (change_pct, volume_ratio, turnover_rate, circ_mv, price):
                continue
            
            # 初步筛选条件
            if not (criteria.change_pct_min <= change_pct <= criteria.change_pct_max):
                continue
            if not (criteria.volume_ratio_min <= volume_ratio <= criteria.volume_ratio_max):
                continue
            if not (criteria.turnover_rate_min <= turnover_rate <= criteria.turnover_rate_max):
                continue
            if not (criteria.circ_mv_min <= circ_mv <= criteria.circ_mv_max):
                continue
            
            # 排除新股（名称以 N 开头）
            if name.startswith('N'):
                continue
            
            results.append(ScreenedStock(
                code=code,
                name=name,
                change_pct=change_pct,
                volume_ratio=volume_ratio,
                turnover_rate=turnover_rate,
                circ_mv=circ_mv,
                price=price
            ))
        
        return results
    
    def _strategy_filter(
        self,
        stocks: List[ScreenedStock],
        strategy: StrategyFilter
    ) -> List[ScreenedStock]:
        """策略过滤：均线排列、乖离率、MACD、成交量、MA60"""
        from data_provider.base import DataFetcherManager
        
        results = []
        manager = DataFetcherManager()
        
        for stock in stocks:
            try:
                # 获取历史数据计算指标（需要60天计算MA60）
                df, _ = manager.get_daily_data(stock.code, days=70)
                
                if df is None or df.empty or len(df) < 30:
                    continue
                
                # 计算均线
                close_col = 'close' if 'close' in df.columns else '收盘'
                volume_col = 'volume' if 'volume' in df.columns else '成交量'
                df['ma5'] = df[close_col].rolling(5).mean()
                df['ma10'] = df[close_col].rolling(10).mean()
                df['ma20'] = df[close_col].rolling(20).mean()
                df['ma60'] = df[close_col].rolling(60).mean()
                
                # 计算 MACD
                ema12 = df[close_col].ewm(span=12, adjust=False).mean()
                ema26 = df[close_col].ewm(span=26, adjust=False).mean()
                df['macd_dif'] = ema12 - ema26
                df['macd_dea'] = df['macd_dif'].ewm(span=9, adjust=False).mean()
                df['macd_bar'] = (df['macd_dif'] - df['macd_dea']) * 2
                
                # 计算成交量均线
                df['vol_ma5'] = df[volume_col].rolling(5).mean()
                df['vol_ma20'] = df[volume_col].rolling(20).mean()
                
                # 取最新数据
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                ma5 = latest['ma5']
                ma10 = latest['ma10']
                ma20 = latest['ma20']
                ma60 = latest['ma60']
                ma60_prev = prev['ma60']
                close_price = latest[close_col]
                macd_dif = latest['macd_dif']
                macd_dea = latest['macd_dea']
                macd_bar = latest['macd_bar']
                vol_ma5 = latest['vol_ma5']
                vol_ma20 = latest['vol_ma20']
                
                # 1. 均线排列判断
                ma_bullish = False
                if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20):
                    if ma5 > ma10 > ma20:
                        ma_bullish = True
                        stock.ma_status = "多头排列"
                    else:
                        stock.ma_status = "非多头排列"
                
                # 2. 乖离率计算
                if pd.notna(ma5) and ma5 > 0:
                    stock.bias_ma5 = (close_price - ma5) / ma5 * 100
                
                # 3. MACD 判断（MACD > 0 且 DIF > DEA）
                macd_positive = False
                if pd.notna(macd_dif) and pd.notna(macd_dea):
                    if macd_bar > 0 and macd_dif > macd_dea:
                        macd_positive = True
                        stock.macd_status = "金叉多头"
                    else:
                        stock.macd_status = "MACD弱势"
                
                # 4. 成交量判断
                volume_up = False
                if pd.notna(vol_ma5) and pd.notna(vol_ma20):
                    if vol_ma5 > vol_ma20:
                        volume_up = True
                        stock.volume_status = "放量"
                    else:
                        stock.volume_status = "缩量"
                
                # 5. MA60 连续3天向上判断
                ma60_up = False
                if len(df) >= 4:
                    ma60_last3 = df['ma60'].iloc[-4:]  # 最近4天的MA60
                    if all(pd.notna(ma60_last3)):
                        # 检查连续3天向上（今天>昨天>前天）
                        if ma60_last3.iloc[-1] > ma60_last3.iloc[-2] > ma60_last3.iloc[-3]:
                            ma60_up = True
                            stock.ma60_status = "连3日↑"
                        elif ma60_last3.iloc[-1] > ma60_last3.iloc[-2]:
                            stock.ma60_status = "向上"
                        elif ma60_last3.iloc[-1] < ma60_last3.iloc[-2]:
                            stock.ma60_status = "向下"
                        else:
                            stock.ma60_status = "走平"
                
                # 策略判断
                passed = True
                
                if strategy.require_ma_bullish and not ma_bullish:
                    passed = False
                
                if stock.bias_ma5 is not None and stock.bias_ma5 > strategy.bias_threshold:
                    passed = False
                
                if strategy.require_macd_positive and not macd_positive:
                    passed = False
                
                if strategy.require_volume_up and not volume_up:
                    passed = False
                
                if strategy.require_ma60_up and not ma60_up:
                    passed = False
                
                stock.passed_strategy = passed
                
                if passed:
                    results.append(stock)
                    
            except Exception as e:
                logger.debug(f"[筛选] {stock.code} 策略过滤失败: {e}")
                continue
        
        return results
    
    def get_stock_codes_only(
        self,
        criteria: Optional[ScreeningCriteria] = None,
        strategy: Optional[StrategyFilter] = None,
        apply_strategy: bool = True
    ) -> List[str]:
        """仅返回股票代码列表"""
        results = self.screen_stocks(criteria, strategy, apply_strategy)
        return [s.code for s in results if s.passed_strategy]


def screen_stocks(
    change_pct_min: float = 3.0,
    change_pct_max: float = 5.0,
    volume_ratio_min: float = 1.0,
    volume_ratio_max: float = 5.0,
    turnover_rate_min: float = 5.0,
    turnover_rate_max: float = 10.0,
    circ_mv_min_yi: float = 50.0,
    circ_mv_max_yi: float = 200.0,
    require_ma_bullish: bool = True,
    bias_threshold: float = 5.0,
    apply_strategy: bool = True
) -> List[str]:
    """
    便捷筛选函数
    
    Args:
        change_pct_min/max: 涨跌幅范围
        volume_ratio_min/max: 量比范围
        turnover_rate_min/max: 换手率范围
        circ_mv_min_yi/max_yi: 流通市值范围（单位：亿）
        require_ma_bullish: 是否要求均线多头排列
        bias_threshold: 乖离率阈值
        apply_strategy: 是否应用策略过滤
        
    Returns:
        股票代码列表
    """
    criteria = ScreeningCriteria(
        change_pct_min=change_pct_min,
        change_pct_max=change_pct_max,
        volume_ratio_min=volume_ratio_min,
        volume_ratio_max=volume_ratio_max,
        turnover_rate_min=turnover_rate_min,
        turnover_rate_max=turnover_rate_max,
        circ_mv_min=circ_mv_min_yi * 1e8,
        circ_mv_max=circ_mv_max_yi * 1e8
    )
    
    strategy = StrategyFilter(
        require_ma_bullish=require_ma_bullish,
        bias_threshold=bias_threshold
    )
    
    service = StockScreeningService()
    return service.get_stock_codes_only(criteria, strategy, apply_strategy)
