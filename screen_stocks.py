# -*- coding: utf-8 -*-
"""
===================================
选股筛选命令行工具
===================================

独立运行筛选功能，无需启动 WebUI。
使用妙想智能选股接口进行自然语言筛选。

用法：
    python screen_stocks.py              # 妙想智能选股
    python screen_stocks.py --analyze    # 筛选后执行AI分析
    python screen_stocks.py --output result.txt  # 输出到文件
    python screen_stocks.py --keyword "换手率3%到10%"  # 自定义筛选条件
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
默认筛选条件（妙想智能选股）：
    - 量比：1 ~ 5
    - 换手率：3% ~ 10%
    - 流通市值：50亿 ~ 200亿
    - 排除：北交所、创业板、科创板、新股、ST
    - MA5 > MA10 > MA20（多头排列）
    - 乖离率 ≤ 5%
    - MACD > 0 且 DIF > DEA
    - 5日均量 > 20日均量
    - MA60 向上
    
示例：
  python screen_stocks.py              # 妙想智能选股
  python screen_stocks.py -a           # 筛选后执行AI分析
  python screen_stocks.py -a --no-notify  # 分析但不推送
  python screen_stocks.py -o codes.txt # 结果保存到文件
  python screen_stocks.py --keyword "换手率5%到15%"  # 自定义筛选条件
        """
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
        "--keyword", "-k",
        type=str,
        default="量比1到5，换手率3%到10%，流通市值50亿到200亿，非北交所，非创业板，非科创板，非新股，非ST，MA5大于MA10大于MA20，乖离率小于等于5%，MACD大于0且DIF大于DEA，5日均量大于20日均量，MA60向上",
        help="妙想选股条件（自然语言）"
    )
        
    args = parser.parse_args()
        
    # 默认使用妙想选股
    return run_mx_screening(args)


def run_mx_screening(args):
    """使用妙想智能选股接口筛选"""
    print("=" * 60)
    print("妙想智能选股")
    print("=" * 60)
    print()
    print(f"筛选条件: {args.keyword}")
    print()
    print("正在查询...")
    
    try:
        from src.services.stock_screening_service import screen_stocks_mx
        
        codes = screen_stocks_mx(keyword=args.keyword, page_size=50)
        
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
