"""订单流转：草稿提交、幂等防重、退回重提。"""
import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.errors import BizError
from app.models import (
    APPROVED,
    DRAFT_SUBMITTED,
    PENDING_SPECIAL,
    REJECTED,
    RETURNED,
    SUBMITTED,
    Draft,
    Order,
    OrderItem,
    User,
)
from app.schemas import DraftData
from app.services import audit, draft_validator, order_no, trade_sync


def _fill_order(order: Order, data: DraftData, total_amount: Decimal, total_qty: Decimal) -> None:
    order.party_name = data.party_name
    order.project_name = data.project_name
    order.address = data.address
    order.contact = data.contact
    order.biz_name = data.biz_name
    order.purchase_mode = data.purchase_mode
    order.biz_tag = data.biz_tag
    order.delivery_date = data.delivery_date
    order.total_amount = total_amount
    order.total_qty = total_qty
    order.remark = data.remark
    order.items = [
        OrderItem(
            seq=idx + 1,
            material_code=i.material_code,
            material_name=i.material_name,
            spec=i.spec,
            quantity=i.quantity,
            unit=i.unit,
            unit_price=i.unit_price,
            amount=i.amount,
        )
        for idx, i in enumerate(data.items)
    ]


async def _existing_order(session: AsyncSession, draft_id: str) -> Order | None:
    return (await session.execute(select(Order).where(Order.draft_id == draft_id))).scalar_one_or_none()


async def submit_draft(
    session: AsyncSession,
    user: User,
    draft_id: str,
    remark: str = "",
    *,
    source: str = "chat",
    today: date | None = None,
) -> tuple[Order, bool]:
    """提交草稿，返回 (订单, 是否本次新建)。

    草稿行加锁使同一草稿的重复提交串行化，已提交时直接返回原订单（FR-033）；
    合同行加锁后重新校验与计算额度，单号在同一事务内生成（C-003）。
    """
    try:
        draft = (
            await session.execute(select(Draft).where(Draft.id == draft_id).with_for_update())
        ).scalar_one_or_none()
        if draft is None or draft.user_id != user.id:
            raise BizError(404, "草稿不存在")
        if draft.order_id is not None:
            order = await session.get(Order, draft.order_id)
            if order is not None and order.status == RETURNED and draft.status != DRAFT_SUBMITTED:
                # 退回订单修改后重提：沿用原单号（FR-038、D-010）
                data = DraftData.model_validate(draft.data)
                if remark:
                    data.remark = remark
                order = await resubmit_order(session, user, order.id, data)
                return order, True
            await session.commit()
            return order, False

        data = DraftData.model_validate(draft.data)
        if remark:
            data.remark = remark
        contract = None
        if data.contract_no:
            contract = await draft_validator.find_contract(session, data.contract_no, for_update=True)
        assembled = await draft_validator.assemble(session, user, data, today=today, contract=contract)
        if assembled.errors:
            draft.data = assembled.data.model_dump(mode="json")
            draft.issues = [i.model_dump() for i in assembled.issues]
            draft.status = assembled.status
            await session.commit()
            raise BizError(422, "草稿存在待确认字段，不能提交", [i.model_dump() for i in assembled.errors])
        q = assembled.quota
        assert q is not None and assembled.contract is not None
        if q.over_quota and not assembled.data.remark.strip():
            raise BizError(422, "本次金额超出合同剩余可下金额，请填写备注后提交")

        data = assembled.data
        no = await order_no.next_order_no(session, data.order_type, user.dept.code, today or clock.today())
        order = Order(
            order_no=no,
            order_type=data.order_type,
            draft_id=draft.id,
            contract_id=assembled.contract.id,
            contract_no=assembled.contract.contract_no,
            dept_id=user.dept_id,
            operator_id=user.id,
            operator_name=user.display_name,
            dept_name=user.dept.name,
            over_quota=q.over_quota,
            status=PENDING_SPECIAL if q.over_quota else SUBMITTED,
            source=source,
        )
        _fill_order(order, data, q.current_amount, q.current_qty)
        session.add(order)
        await session.flush()
        await trade_sync.sync_order(session, order)

        draft.order_id = order.id
        draft.status = DRAFT_SUBMITTED
        draft.data = data.model_dump(mode="json")
        draft.issues = [i.model_dump() for i in assembled.issues]
        audit.record(
            session,
            user,
            audit.SUBMIT,
            order_no=no,
            detail={"draft_id": draft.id, "over_quota": q.over_quota, "amount": str(q.current_amount), "source": source},
        )
        await session.commit()
        return order, True
    except IntegrityError:
        # draft_id 唯一索引兜底：返回已存在的订单
        await session.rollback()
        order = await _existing_order(session, draft_id)
        if order is None:
            raise
        return order, False
    except BaseException:
        await session.rollback()
        raise


async def submit_with_retry(session: AsyncSession, user: User, draft_id: str, remark: str, source: str = "chat"):
    """MySQL 死锁（1213）或锁等待超时（1205）时重试。"""
    for attempt in range(3):
        try:
            return await submit_draft(session, user, draft_id, remark, source=source)
        except OperationalError as e:
            code = e.orig.args[0] if e.orig is not None and e.orig.args else None
            if code not in (1205, 1213) or attempt == 2:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))
    raise RuntimeError("unreachable")


async def resubmit_order(session: AsyncSession, user: User, order_id: int, data: DraftData) -> Order:
    """退回订单修改后重提：沿用原单号，重算额度时排除自身占用（FR-038、D-010）。"""
    try:
        order = (
            await session.execute(select(Order).where(Order.id == order_id).with_for_update())
        ).scalar_one_or_none()
        if order is None or order.dept_id != user.dept_id or order.operator_id != user.id:
            raise BizError(404, "订单不存在")
        if order.status != RETURNED:
            raise BizError(409, "只有被退回的订单可以修改后重新提交")
        data = data.model_copy(update={"order_type": order.order_type})
        contract = None
        if data.contract_no:
            contract = await draft_validator.find_contract(session, data.contract_no, for_update=True)
        assembled = await draft_validator.assemble(session, user, data, contract=contract, exclude_order_id=order.id)
        if assembled.errors:
            raise BizError(422, "订单存在待确认字段，不能提交", [i.model_dump() for i in assembled.errors])
        q = assembled.quota
        assert q is not None and assembled.contract is not None
        if q.over_quota and not assembled.data.remark.strip():
            raise BizError(422, "本次金额超出合同剩余可下金额，请填写备注后提交")
        order.contract_id = assembled.contract.id
        order.contract_no = assembled.contract.contract_no
        order.over_quota = q.over_quota
        order.status = PENDING_SPECIAL if q.over_quota else SUBMITTED
        order.approval_comment = ""
        _fill_order(order, assembled.data, q.current_amount, q.current_qty)
        await session.flush()
        await trade_sync.sync_order(session, order)
        draft = (await session.execute(select(Draft).where(Draft.id == order.draft_id))).scalar_one_or_none()
        if draft is not None:
            draft.data = assembled.data.model_dump(mode="json")
            draft.issues = [i.model_dump() for i in assembled.issues]
            draft.status = DRAFT_SUBMITTED
        audit.record(
            session,
            user,
            audit.RESUBMIT,
            order_no=order.order_no,
            detail={"over_quota": q.over_quota, "amount": str(q.current_amount)},
        )
        await session.commit()
        return order
    except BaseException:
        await session.rollback()
        raise


REVIEW_ACTIONS = {
    APPROVED: audit.APPROVE,
    RETURNED: audit.RETURN,
    REJECTED: audit.REJECT,
}
REVIEWABLE = (SUBMITTED, PENDING_SPECIAL)


async def review_order(session: AsyncSession, user: User, order_id: int, to_status: str, comment: str = "") -> Order:
    """审批：通过、退回、驳回；退回和驳回必须填写意见（FR-037）。订单行加锁防止并发审批。"""
    try:
        order = (
            await session.execute(select(Order).where(Order.id == order_id).with_for_update())
        ).scalar_one_or_none()
        if order is None or order.dept_id != user.dept_id:
            raise BizError(404, "订单不存在")
        if order.status not in REVIEWABLE:
            raise BizError(409, "只有已提交或待特批的订单可以审批")
        comment = comment.strip()
        if to_status in (RETURNED, REJECTED) and not comment:
            raise BizError(422, "退回和驳回必须填写审批意见")
        prev = order.status
        order.status = to_status
        order.approval_comment = comment
        await trade_sync.sync_order(session, order)
        audit.record(
            session,
            user,
            REVIEW_ACTIONS[to_status],
            order_no=order.order_no,
            detail={"comment": comment, "from": prev, "over_quota": order.over_quota},
        )
        await session.commit()
        return order
    except BaseException:
        await session.rollback()
        raise


async def reopen_returned(session: AsyncSession, user: User, order_id: int) -> tuple[Draft, Order]:
    """经办人修改被退回的订单：把订单对应的草稿重新打开，载入工作台继续编辑（FR-046）。"""
    order = await session.get(Order, order_id)
    if order is None or order.dept_id != user.dept_id or order.operator_id != user.id:
        raise BizError(404, "订单不存在")
    if order.status != RETURNED:
        raise BizError(409, "只有被退回的订单可以修改")
    draft = await session.get(Draft, order.draft_id)
    if draft is None:
        raise BizError(404, "订单对应的草稿不存在")
    data = DraftData.model_validate(draft.data)
    assembled = await draft_validator.assemble(session, user, data, exclude_order_id=order.id)
    draft.data = assembled.data.model_dump(mode="json")
    draft.issues = [i.model_dump() for i in assembled.issues]
    draft.status = assembled.status
    await session.commit()
    return draft, order
