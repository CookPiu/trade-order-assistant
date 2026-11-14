"""订单审批（FR-037、US5）：审批人在详情抽屉中通过、退回或驳回本部门已提交、待特批的订单。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.orders import OrderDetail, order_detail
from app.core.db import get_session
from app.core.security import require_roles
from app.models import APPROVED, REJECTED, RETURNED, ROLE_APPROVER, User
from app.services import order_flow

router = APIRouter(prefix="/api/orders", tags=["approval"])
approver = require_roles(ROLE_APPROVER)


class ReviewRequest(BaseModel):
    comment: str = ""


async def _review(session: AsyncSession, user: User, order_id: int, to_status: str, comment: str) -> OrderDetail:
    order = await order_flow.review_order(session, user, order_id, to_status, comment)
    return await order_detail(session, order)


@router.post("/{order_id}/approve", response_model=OrderDetail)
async def approve(
    order_id: int, body: ReviewRequest, user: User = Depends(approver), session: AsyncSession = Depends(get_session)
):
    return await _review(session, user, order_id, APPROVED, body.comment)


@router.post("/{order_id}/return", response_model=OrderDetail)
async def return_order(
    order_id: int, body: ReviewRequest, user: User = Depends(approver), session: AsyncSession = Depends(get_session)
):
    return await _review(session, user, order_id, RETURNED, body.comment)


@router.post("/{order_id}/reject", response_model=OrderDetail)
async def reject(
    order_id: int, body: ReviewRequest, user: User = Depends(approver), session: AsyncSession = Depends(get_session)
):
    return await _review(session, user, order_id, REJECTED, body.comment)
