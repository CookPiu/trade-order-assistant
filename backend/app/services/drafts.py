"""草稿持久化与视图组装。"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError
from app.models import DRAFT_SUBMITTED, Draft, Order, User
from app.schemas import DraftData, DraftView
from app.services import draft_validator


def view_of(draft: Draft, assembled: draft_validator.Assembled | None = None, order: Order | None = None) -> DraftView:
    if assembled is not None:
        return DraftView(
            id=draft.id,
            session_id=draft.session_id,
            status=draft.status,
            data=assembled.data,
            issues=assembled.issues,
            quota=assembled.quota_summary(),
            order_no=order.order_no if order else None,
            order_status=order.status if order else None,
            approval_comment=order.approval_comment if order else "",
        )
    return DraftView(
        id=draft.id,
        session_id=draft.session_id,
        status=draft.status,
        data=DraftData.model_validate(draft.data),
        issues=draft.issues or [],
        order_no=order.order_no if order else None,
        order_status=order.status if order else None,
        approval_comment=order.approval_comment if order else "",
    )


async def load_own(session: AsyncSession, user: User, draft_id: str) -> Draft:
    draft = await session.get(Draft, draft_id)
    if draft is None or draft.user_id != user.id:
        raise BizError(404, "草稿不存在")
    return draft


async def save(
    session: AsyncSession, user: User, data: DraftData, *, draft_id: str | None, session_id: str
) -> tuple[Draft, draft_validator.Assembled]:
    """新建或更新草稿并重新校验。已提交的草稿不能再改。调用方负责 commit。"""
    if draft_id:
        draft = await load_own(session, user, draft_id)
        if draft.status == DRAFT_SUBMITTED:
            raise BizError(409, "草稿已提交，不能修改")
    else:
        draft = Draft(id=str(uuid.uuid4()), session_id=session_id, user_id=user.id, dept_id=user.dept_id)
    # 退回订单重新打开的草稿带 order_id，额度计算排除该订单原有占用（FR-038）
    assembled = await draft_validator.assemble(session, user, data, exclude_order_id=draft.order_id)
    draft.order_type = assembled.data.order_type
    draft.data = assembled.data.model_dump(mode="json")
    draft.issues = [i.model_dump() for i in assembled.issues]
    draft.status = assembled.status
    # 校验完成后再加入会话，避免校验中的查询触发未填完整的草稿提前 flush
    session.add(draft)
    return draft, assembled


async def persist(
    session: AsyncSession,
    user: User,
    assembled: draft_validator.Assembled,
    *,
    draft_id: str | None,
    session_id: str,
) -> Draft:
    """保存已装配的草稿；原草稿已提交或不存在时新建。调用方负责 commit。"""
    draft = None
    if draft_id:
        draft = await load_own(session, user, draft_id)
        if draft.status == DRAFT_SUBMITTED:
            draft = None
    if draft is None:
        draft = Draft(id=str(uuid.uuid4()), session_id=session_id, user_id=user.id, dept_id=user.dept_id)
    draft.order_type = assembled.data.order_type
    draft.data = assembled.data.model_dump(mode="json")
    draft.issues = [i.model_dump() for i in assembled.issues]
    draft.status = assembled.status
    session.add(draft)
    return draft


async def full_view(session: AsyncSession, user: User, draft: Draft) -> DraftView:
    order = await session.get(Order, draft.order_id) if draft.order_id else None
    if draft.status == DRAFT_SUBMITTED:
        view = view_of(draft, order=order)
        if order is not None:
            # 已提交草稿仍展示额度：累计已下排除本单，本次占用即本单金额
            assembled = await draft_validator.assemble(
                session, user, view.data, exclude_order_id=order.id
            )
            view.quota = assembled.quota_summary()
        return view
    assembled = await draft_validator.assemble(
        session, user, DraftData.model_validate(draft.data), exclude_order_id=draft.order_id
    )
    return view_of(draft, assembled, order)


async def latest_open(session: AsyncSession, user: User) -> Draft | None:
    stmt = (
        select(Draft)
        .where(Draft.user_id == user.id, Draft.status != DRAFT_SUBMITTED)
        .order_by(Draft.updated_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
