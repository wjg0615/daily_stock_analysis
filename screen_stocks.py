# -*- coding: utf-8 -*-
"""
===================================
选股筛选命令行工具
===================================

独立运行筛选功能，无需启动 WebUI。

用法：
    python screen_stocks.py              # 完整筛选（初步筛选 + 策略过滤）
    python screen_stocks.py --quick      # 快速筛选（仅初步筛选）
    python screen_stocks.py --analyze    # 筛选后执行AI分析
    python screen_stocks.py --output result.txt  # 输出到文件
"""

import argparse
import logging
import sys

from src.config import setup_env
setup_env()

from src.logging_config import setup_logging
setup_logging(log_prefix="screen_stocks")

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="股票筛选工具 - 从沪深A股中筛选符合条件的股票",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
筛选条件：
  初步筛选：
    - 量比：1 ~ 5
    - 换手率：3% ~ 10%
    - 流通市值：50亿 ~ 200亿
    - 排除北交所、创业板、科创板、新股

  策略过滤（默认启用）：
    - MA5 > MA10 > MA20（多头排列）
    - 乖离率 ≤ 5%
    - MACD > 0 且 DIF > DEA
    - 成交量：5日均量 > 20日均量
    - MA60：斜率 > 0（向上）
    
示例：
  python screen_stocks.py              # 完整筛选
  python screen_stocks.py --quick      # 快速筛选
  python screen_stocks.py --analyze    # 筛选后执行AI分析
  python screen_stocks.py -a --no-notify  # 分析但不推送
  python screen_stocks.py -o codes.txt # 结果保存到文件
  python screen_stocks.py --no-cache   # 强制重新筛选
        """
    )
    
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="快速筛选（仅初步筛选，不应用策略过滤）"
    )
    parser.add_argument(
        "--no-strategy",
        action="store_true",
        help="同 --quick，不应用策略过滤"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出文件路径（默认打印到控制台）"
    )
    parser.add_argument(
        "--codes-only",
        action="store_true",
        help="仅输出股票代码（逗号分隔）"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="不使用缓存，重新执行筛选"
    )
    parser.add_argument(
        "--analyze", "-a",
        action="store_true",
        help="筛选后执行AI分析（调用主分析流程）"
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="分析后不发送推送通知（配合--analyze使用）"
    )
    parser.add_argument(
        "--mx",
        action="store_true",
        help="使用妙想智能选股接口（自然语言筛选，需配置MX_APIKEY）"
    )
    parser.add_argument(
        "--mx-keyword",
        type=str,
        default="量比1到5，换手率3%到10%，流通市值50亿到200亿，非北交所，非创业板，非科创板，非新股，MA5大于MA10大于MA20，乖离率小于等于5%，MACD大于0且DIF大于DEA，5日均量大于20日均量，MA60向上",
        help="妙想选股条件（配合--mx使用）"
    )
    
    args = parser.parse_args()
    
    # 使用妙想选股
    if args.mx:
        return run_mx_screening(args)
    
    apply_strategy = not (args.quick or args.no_strategy)
    
    print("=" * 60)
    print("股票筛选工具")
    print("=" * 60)
    print()
    
    if apply_strategy:
        print("筛选模式：完整筛选（初步筛选 + 策略过滤）")
    else:
        print("筛选模式：快速筛选（仅初步筛选）")
    print()
    
    print("筛选条件：")
    print("  - 量比：1 ~ 5")
    print("  - 换手率：3% ~ 10%")
    print("  - 流通市值：50亿 ~ 200亿")
    print("  - 排除：北交所、创业板、科创板、新股")
    if apply_strategy:
        print("  - 均线排列：MA5 > MA10 > MA20")
        print("  - 乖离率：≤ 5%")
        print("  - MACD：MACD > 0 且 DIF > DEA")
        print("  - 成交量：5日均量 > 20日均量")
        print("  - MA60：斜率 > 0（向上）")
    print()
    print("正在获取数据...")
    print()
    
    try:
        from src.services.stock_screening_service import (
            StockScreeningService,
            ScreeningCriteria,
            StrategyFilter
        )
        
        service = StockScreeningService()
        criteria = ScreeningCriteria()
        strategy = StrategyFilter()
        
        results = service.screen_stocks(
            criteria=criteria,
            strategy=strategy,
            apply_strategy=apply_strategy,
            use_cache=not args.no_cache
        )
        
        if not results:
            print("📭 筛选结果为空，当前市场没有符合条件的股票。")
            return 0
        
        # 按涨跌幅排序
        results.sort(key=lambda x: x.change_pct, reverse=True)
        
        # 构建输出
        lines = []
        lines.append(f"筛选结果（共 {len(results)} 只）：")
        lines.append("")
        
        for stock in results:
            status = "✅" if stock.passed_strategy else "⏳"
            mv_yi = stock.circ_mv / 1e8
            bias_str = f"{stock.bias_ma5:.1f}%" if stock.bias_ma5 else "-"
            line = f"{status} {stock.code} {stock.name} | 涨{stock.change_pct:.1f}% | 量比{stock.volume_ratio:.1f} | 换手{stock.turnover_rate:.1f}% | 市值{mv_yi:.0f}亿"
            lines.append(line)
            
            # 策略状态详情
            if apply_strategy:
                detail_parts = []
                if stock.ma_status:
                    detail_parts.append(stock.ma_status)
                if stock.bias_ma5 is not None:
                    detail_parts.append(f"乖离{bias_str}")
                if stock.macd_status:
                    detail_parts.append(stock.macd_status)
                if stock.volume_status:
                    detail_parts.append(stock.volume_status)
                if stock.ma60_status:
                    detail_parts.append(f"MA60{stock.ma60_status}")
                if detail_parts:
                    lines.append(f"   └─ {' | '.join(detail_parts)}")
        
        # 股票代码列表
        codes = [s.code for s in results if s.passed_strategy or not apply_strategy]
        
        if args.codes_only:
            output_text = ", ".join(codes)
        else:
            lines.append("")
            lines.append("=" * 60)
            lines.append("股票代码列表（可直接复制）：")
            lines.append(", ".join(codes[:50]))
            output_text = "\n".join(lines)
        
        # 输出
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_text)
            print(output_text)
            print()
            print(f"✅ 结果已保存到: {args.output}")
        else:
            print(output_text)
        
        # 执行AI分析
        if args.analyze and codes:
            print()
            print("=" * 60)
            print("开始执行AI分析...")
            print("=" * 60)
            print()
            
            try:
                import uuid
                from src.config import get_config
                from src.core.pipeline import StockAnalysisPipeline
                
                config = get_config()
                query_id = uuid.uuid4().hex
                pipeline = StockAnalysisPipeline(
                    config=config,
                    query_id=query_id,
                    query_source="screen_stocks"
                )
                
                # 运行分析
                analysis_results = pipeline.run(
                    stock_codes=codes,
                    dry_run=False,
                    send_notification=not args.no_notify
                )
                
                # 输出分析结果摘要
                if analysis_results:
                    print()
                    print("=" * 60)
                    print("分析结果摘要")
                    print("=" * 60)
                    for r in sorted(analysis_results, key=lambda x: x.sentiment_score, reverse=True):
                        emoji = r.get_emoji()
                        print(f"{emoji} {r.name}({r.code}): {r.operation_advice} | 评分 {r.sentiment_score}")
                else:
                    print("⚠️ 分析结果为空")
                
            except Exception as e:
                logger.error(f"AI分析失败: {e}")
                print(f"❌ AI分析失败: {e}")
                return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"筛选失败: {e}")
        print(f"❌ 筛选失败: {e}")
        return 1


def run_mx_screening(args):
    """使用妙想智能选股接口筛选"""
    print("=" * 60)
    print("妙想智能选股")
    print("=" * 60)
    print()
    print(f"筛选条件: {args.mx_keyword}")
    print()
    print("正在查询...")
    
    try:
        from src.services.stock_screening_service import screen_stocks_mx
        
        codes = screen_stocks_mx(keyword=args.mx_keyword, page_size=50)
        
        if not codes:
            print("📭 筛选结果为空，当前市场没有符合条件的股票。")
            return 0
        
        print(f"\n筛选结果（共 {len(codes)} 只）：")
        print()
        print("股票代码列表：")
        print(", ".join(codes))
        
        # 输出到文件
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(", ".join(codes))
            print(f"\n✅ 结果已保存到: {args.output}")
        
        # 执行AI分析
        if args.analyze and codes:
            print()
            print("=" * 60)
            print("开始执行AI分析...")
            print("=" * 60)
            
            try:
                import uuid
                from src.config import get_config
                from src.core.pipeline import StockAnalysisPipeline
                
                config = get_config()
                query_id = uuid.uuid4().hex
                pipeline = StockAnalysisPipeline(
                    config=config,
                    query_id=query_id,
                    query_source="screen_stocks_mx"
                )
                
                analysis_results = pipeline.run(
                    stock_codes=codes,
                    dry_run=False,
                    send_notification=not args.no_notify
                )
                
                if analysis_results:
                    print()
                    print("=" * 60)
                    print("分析结果摘要")
                    print("=" * 60)
                    for r in sorted(analysis_results, key=lambda x: x.sentiment_score, reverse=True):
                        emoji = r.get_emoji()
                        print(f"{emoji} {r.name}({r.code}): {r.operation_advice} | 评分 {r.sentiment_score}")
                else:
                    print("⚠️ 分析结果为空")
                
            except Exception as e:
                logger.error(f"AI分析失败: {e}")
                print(f"❌ AI分析失败: {e}")
                return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"妙想选股失败: {e}")
        print(f"❌ 妙想选股失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
