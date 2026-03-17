# -*- coding: utf-8 -*-
"""
单独发送报告邮件的脚本

使用方式:
    python send_report_email.py                    # 发送今天的报告
    python send_report_email.py --file reports/report_20260318.md   # 发送指定报告
"""
import argparse
import os
import sys
from pathlib import Path

# 初始化环境
from src.config import setup_env
setup_env()

from src.config import get_config
from src.notification_sender.email_sender import EmailSender


def main():
    parser = argparse.ArgumentParser(description='发送股票分析报告邮件')
    parser.add_argument(
        '--file', '-f',
        type=str,
        default=None,
        help='报告文件路径 (默认: reports/report_YYYYMMDD.md)'
    )
    parser.add_argument(
        '--subject', '-s',
        type=str,
        default=None,
        help='邮件主题 (默认: 自动生成)'
    )
    parser.add_argument(
        '--receivers', '-r',
        type=str,
        default=None,
        help='收件人邮箱，多个用逗号分隔 (默认: 使用配置的收件人)'
    )
    args = parser.parse_args()

    # 确定报告文件路径
    if args.file:
        report_path = Path(args.file)
    else:
        # 默认今天的报告
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        report_path = Path(f'reports/report_{date_str}.md')

    if not report_path.exists():
        print(f"❌ 报告文件不存在: {report_path}")
        sys.exit(1)

    # 读取报告内容
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"📄 已读取报告: {report_path} ({len(content)} 字符)")

    # 初始化邮件发送器
    config = get_config()
    sender = EmailSender(config)

    # 检查邮件配置
    if not config.email_sender or not config.email_password:
        print("❌ 邮件配置不完整，请检查 .env 中的 EMAIL_SENDER 和 EMAIL_PASSWORD")
        sys.exit(1)

    # 确定收件人
    receivers = None
    if args.receivers:
        receivers = [r.strip() for r in args.receivers.split(',')]
    else:
        receivers = sender.get_all_email_receivers()

    if not receivers:
        print("❌ 未配置收件人，请检查 .env 中的 EMAIL_RECEIVERS")
        sys.exit(1)

    print(f"📧 发件人: {config.email_sender}")
    print(f"📧 收件人: {receivers}")

    # 发送邮件
    subject = args.subject
    success = sender.send_to_email(content, subject=subject, receivers=receivers)

    if success:
        print("✅ 邮件发送成功!")
    else:
        print("❌ 邮件发送失败，请检查日志")
        sys.exit(1)


if __name__ == "__main__":
    main()
