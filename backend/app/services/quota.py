"""合同额度计算：四项统计、超额判定、公允价与配额阈值提醒。"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import REJECTED, Order

ZERO = Decimal("0")


@dataclass
class Usage:
    amount: Decimal = ZERO
    qty: Decimal = ZERO


@dataclass
class QuotaResult:
    total_amount: Decimal
    used_amount: Decimal
    remaining_amount: Decimal
    total_qty: Decimal
    used_qty: Decimal
    remaining_qty: Decimal
    current_amount: Decimal
    current_qty: Decimal
    after_remaining_amount: Decimal
    over_quota: bool  # 本次金额超出剩余可下金额（FR-022）
    qty_exceeded: bool  # 本次数量超出剩余可下数量（FR-025，只做提示）
    low_quota: bool  # 提交后剩余金额占比低于阈值（FR-028）


def evaluate(
    total_amount: Decimal,
    total_qty: Decimal,
    usage: Usage,
    current_amount: Decimal,
    current_qty: Decimal,
    warn_ratio: float,
) -> QuotaResult:
    remaining_amount = total_amount - usage.amount
    remaining_qty = total_qty - usage.qty
    after = remaining_amount - current_amount
    over = current_amount > remaining_amount
    low = (not over) and total_amount > 0 and after / total_amount < Decimal(str(warn_ratio))
    return QuotaResult(
        total_amount=total_amount,
        used_amount=usage.amount,
        remaining_amount=remaining_amount,
        total_qty=total_qty,
        used_qty=usage.qty,
        remaining_qty=remaining_qty,
        current_amount=current_amount,
        current_qty=current_qty,
        after_remaining_amount=after,
        over_quota=over,
        qty_exceeded=current_qty > remaining_qty,
        low_quota=low,
    )


def fair_price_deviates(unit_price: Decimal, fair_price: Decimal | None, ratio: float) -> bool:
    if fair_price is None or fair_price <= 0:
        return False
    return abs(unit_price - fair_price) / fair_price > Decimal(str(ratio))


async def contract_usage(session: AsyncSession, contract_id: int, exclude_order_id: int | None = None) -> Usage:
    """累计已下金额与数量：驳回之外的订单都计入（FR-026）。"""
    stmt = select(func.coalesce(func.sum(Order.total_amount), 0), func.coalesce(func.sum(Order.total_qty), 0)).where(
        Order.contract_id == contract_id, Order.status != REJECTED
    )
    if exclude_order_id is not None:
        stmt = stmt.where(Order.id != exclude_order_id)
    amount, qty = (await session.execute(stmt)).one()
    return Usage(amount=Decimal(amount), qty=Decimal(qty))
