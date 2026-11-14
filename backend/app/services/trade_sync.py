"""把正式订单同步到模拟的底层商贸系统表（FR-034），与订单写入同一事务。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SALES, Order, TradePurchaseOrder, TradeSalesOrder


def order_payload(order: Order) -> dict:
    return {
        "order_no": order.order_no,
        "order_type": order.order_type,
        "contract_no": order.contract_no,
        "party_name": order.party_name,
        "project_name": order.project_name,
        "address": order.address,
        "contact": order.contact,
        "operator_name": order.operator_name,
        "dept_name": order.dept_name,
        "delivery_date": order.delivery_date.isoformat(),
        "total_amount": str(order.total_amount),
        "status": order.status,
        "items": [
            {
                "seq": i.seq,
                "material_code": i.material_code,
                "material_name": i.material_name,
                "spec": i.spec,
                "quantity": str(i.quantity),
                "unit": i.unit,
                "unit_price": str(i.unit_price),
                "amount": str(i.amount),
            }
            for i in order.items
        ],
    }


async def sync_order(session: AsyncSession, order: Order) -> None:
    model = TradeSalesOrder if order.order_type == SALES else TradePurchaseOrder
    row = (await session.execute(select(model).where(model.order_no == order.order_no))).scalar_one_or_none()
    if row is None:
        row = model(order_no=order.order_no)
        session.add(row)
    row.contract_no = order.contract_no
    row.party_name = order.party_name
    row.total_amount = order.total_amount
    row.status = order.status
    row.payload = order_payload(order)
