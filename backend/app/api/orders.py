"""模拟商贸系统订单列表与详情（FR-035、FR-002、US4）。按部门隔离，经办人与审批人可访问。"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import BizError
from app.core.security import require_roles
from app.models import ROLE_APPROVER, ROLE_OPERATOR, AuditLog, Contract, Order, User
from app.schemas import DraftView, QuotaSummary
from app.services import drafts, order_flow, quota

router = APIRouter(prefix="/api/orders", tags=["orders"])
reader = require_roles(ROLE_OPERATOR, ROLE_APPROVER)
operator = require_roles(ROLE_OPERATOR)

STATUSES = {"submitted", "pending_special", "approved", "returned", "rejected"}
# 审批人在列表中只看本部门待审订单（DESIGN 4.6）；详情仍可打开，审批后能看到处理结果
APPROVER_STATUSES = {"submitted", "pending_special"}


class OrderRow(BaseModel):
    id: int
    order_no: str
    order_type: str
    contract_no: str
    party_name: str
    project_name: str
    total_amount: Decimal
    status: str
    over_quota: bool
    operator_name: str
    source: str
    submitted_at: datetime | None


class OrderPage(BaseModel):
    total: int
    items: list[OrderRow]


class OrderItemView(BaseModel):
    seq: int
    material_code: str
    material_name: str
    spec: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    amount: Decimal


class AuditView(BaseModel):
    action: str
    username: str
    created_at: datetime | None
    detail: dict


class OrderDetail(OrderRow):
    address: str
    contact: str
    dept_name: str
    biz_name: str
    purchase_mode: str
    biz_tag: str
    delivery_date: date
    total_qty: Decimal
    remark: str
    approval_comment: str
    operator_id: int
    items: list[OrderItemView]
    quota: QuotaSummary | None
    audits: list[AuditView]


def _row(o: Order) -> OrderRow:
    return OrderRow.model_validate(o, from_attributes=True)


@router.get("", response_model=OrderPage)
async def list_orders(
    order_type: Literal["sales", "purchase"] | None = None,
    status: str | None = Query(None, description="逗号分隔的状态"),
    contract_no: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(reader),
    session: AsyncSession = Depends(get_session),
):
    conds = [Order.dept_id == user.dept_id]
    if order_type:
        conds.append(Order.order_type == order_type)
    allowed = APPROVER_STATUSES if user.role == ROLE_APPROVER else STATUSES
    wanted = [s for s in (status or "").split(",") if s in allowed]
    if wanted:
        conds.append(Order.status.in_(wanted))
    elif user.role == ROLE_APPROVER:
        conds.append(Order.status.in_(APPROVER_STATUSES))
    if contract_no and contract_no.strip():
        conds.append(Order.contract_no.contains(contract_no.strip()))
    if date_from:
        conds.append(Order.submitted_at >= datetime.combine(date_from, time.min))
    if date_to:
        conds.append(Order.submitted_at < datetime.combine(date_to + timedelta(days=1), time.min))
    total = (await session.execute(select(func.count()).select_from(Order).where(*conds))).scalar_one()
    stmt = (
        select(Order)
        .where(*conds)
        .order_by(Order.submitted_at.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return OrderPage(total=total, items=[_row(o) for o in rows])


async def load_order(session: AsyncSession, user: User, order_id: int) -> Order:
    order = await session.get(Order, order_id)
    if order is None or order.dept_id != user.dept_id:
        raise BizError(404, "订单不存在")
    return order


async def order_detail(session: AsyncSession, order: Order) -> OrderDetail:
    contract = await session.get(Contract, order.contract_id)
    summary = None
    if contract is not None:
        # 累计已下排除本单；驳回订单不占额度，剩余额度不扣减本单
        used = await quota.contract_usage(session, contract.id, exclude_order_id=order.id)
        remaining = contract.total_amount - used.amount
        occupies = order.status != "rejected"
        summary = QuotaSummary(
            contract_no=contract.contract_no,
            unit=contract.unit,
            total_amount=contract.total_amount,
            used_amount=used.amount,
            remaining_amount=remaining,
            total_qty=contract.total_qty,
            used_qty=used.qty,
            remaining_qty=contract.total_qty - used.qty,
            current_amount=order.total_amount,
            current_qty=order.total_qty,
            after_remaining_amount=remaining - order.total_amount if occupies else remaining,
            over_quota=order.over_quota,
            low_quota=False,
        )
    audits = (
        await session.execute(
            select(AuditLog).where(AuditLog.order_no == order.order_no).order_by(AuditLog.created_at, AuditLog.id)
        )
    ).scalars().all()
    return OrderDetail(
        **_row(order).model_dump(),
        address=order.address,
        contact=order.contact,
        dept_name=order.dept_name,
        biz_name=order.biz_name,
        purchase_mode=order.purchase_mode,
        biz_tag=order.biz_tag,
        delivery_date=order.delivery_date,
        total_qty=order.total_qty,
        remark=order.remark,
        approval_comment=order.approval_comment,
        operator_id=order.operator_id,
        items=[OrderItemView.model_validate(i, from_attributes=True) for i in order.items],
        quota=summary,
        audits=[
            AuditView(action=a.action, username=a.username, created_at=a.created_at, detail=a.detail or {})
            for a in audits
        ],
    )


@router.get("/{order_id}", response_model=OrderDetail)
async def get_order(order_id: int, user: User = Depends(reader), session: AsyncSession = Depends(get_session)):
    return await order_detail(session, await load_order(session, user, order_id))


@router.post("/{order_id}/edit", response_model=DraftView)
async def edit_returned(order_id: int, user: User = Depends(operator), session: AsyncSession = Depends(get_session)):
    """经办人修改被退回的订单：重新打开对应草稿，返回草稿视图载入工作台（FR-046）。"""
    draft, _ = await order_flow.reopen_returned(session, user, order_id)
    return await drafts.full_view(session, user, draft)
