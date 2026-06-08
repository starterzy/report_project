"""
填报提醒定时脚本
通过 systemd timer 触发，每月8号全员提醒，每月10号未填报提醒。
"""
import sys
import os
import argparse
from datetime import datetime
import asyncio

# 确保 backend 模块可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from backend.services.notification_service import notify_task_reminders, check_and_notify_unfilled


def main():
    parser = argparse.ArgumentParser(description="重点工作任务填报提醒")
    parser.add_argument(
        "--mode",
        choices=["monthly", "check"],
        required=True,
        help="monthly: 每月8号全员提醒; check: 每月10号未填报提醒",
    )
    parser.add_argument(
        "--month",
        default=None,
        help="指定月份 YYYY-MM（默认当前月份），仅 check 模式可用",
    )
    args = parser.parse_args()

    now = datetime.now()
    year = now.year

    if args.mode == "monthly":
        print(f"[{now}] 执行全员填报提醒 (年度 {year})")
        asyncio.run(notify_task_reminders(year))
        print(f"[{datetime.now()}] 全员填报提醒完成")

    elif args.mode == "check":
        month = args.month or now.strftime("%Y-%m")
        print(f"[{now}] 执行未填报检查提醒 (月份 {month})")
        asyncio.run(check_and_notify_unfilled(year, month))
        print(f"[{datetime.now()}] 未填报检查提醒完成")


if __name__ == "__main__":
    main()
