"""业务时钟：按配置的 UTC 偏移取当前时间，不依赖进程的 TZ 环境变量。

交期换算、单号日期、创建时间都以此为准。Windows 上 TZ 设为 IANA 名称时 Python 会退回 UTC，
直接用 datetime.now() 会差出整整一个时区。
"""
from datetime import date, datetime, timedelta, timezone

from app.core.config import get_settings


def now() -> datetime:
    tz = timezone(timedelta(hours=get_settings().app_utc_offset_hours))
    return datetime.now(tz).replace(tzinfo=None)


def today() -> date:
    return now().date()
