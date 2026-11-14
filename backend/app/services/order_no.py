"""单号生成：前缀-单位代码-yyyyMMdd-三位流水号，在调用方事务内加行锁递增（C-003）。"""
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PREFIX = {"sales": "XSDD", "purchase": "CGDD"}


async def next_order_no(session: AsyncSession, order_type: str, unit_code: str, biz_date: date) -> str:
    prefix = PREFIX[order_type]
    day = biz_date.strftime("%Y%m%d")
    # 插入或递增都会对该行加排他锁，直到事务结束
    await session.execute(
        text(
            "INSERT INTO order_no_seq (prefix, unit_code, biz_date, last_seq) VALUES (:p, :u, :d, 1) "
            "ON DUPLICATE KEY UPDATE last_seq = last_seq + 1"
        ),
        {"p": prefix, "u": unit_code, "d": day},
    )
    seq = (
        await session.execute(
            text("SELECT last_seq FROM order_no_seq WHERE prefix=:p AND unit_code=:u AND biz_date=:d FOR UPDATE"),
            {"p": prefix, "u": unit_code, "d": day},
        )
    ).scalar_one()
    return f"{prefix}-{unit_code}-{day}-{seq:03d}"
