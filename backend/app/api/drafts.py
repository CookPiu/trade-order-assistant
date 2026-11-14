"""草稿保存、载入与提交（FR-004、FR-032、FR-033）。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import require_roles
from app.models import ROLE_OPERATOR, User
from app.schemas import DraftData, SubmitRequest
from app.services import audit, drafts
from app.services.order_flow import submit_with_retry

router = APIRouter(prefix="/api/drafts", tags=["drafts"])
operator = require_roles(ROLE_OPERATOR)


class SaveRequest(BaseModel):
    session_id: str
    draft_id: str | None = None
    data: DraftData


@router.post("")
async def save_draft(body: SaveRequest, user: User = Depends(operator), session: AsyncSession = Depends(get_session)):
    draft, assembled = await drafts.save(session, user, body.data, draft_id=body.draft_id, session_id=body.session_id)
    audit.record(session, user, audit.DRAFT_SAVE, detail={"draft_id": draft.id})
    await session.commit()
    return drafts.view_of(draft, assembled)


@router.get("/latest")
async def latest_draft(user: User = Depends(operator), session: AsyncSession = Depends(get_session)):
    draft = await drafts.latest_open(session, user)
    if draft is None:
        return None
    return await drafts.full_view(session, user, draft)


@router.get("/{draft_id}")
async def get_draft(draft_id: str, user: User = Depends(operator), session: AsyncSession = Depends(get_session)):
    draft = await drafts.load_own(session, user, draft_id)
    return await drafts.full_view(session, user, draft)


@router.post("/{draft_id}/submit")
async def submit(
    draft_id: str, body: SubmitRequest, user: User = Depends(operator), session: AsyncSession = Depends(get_session)
):
    order, created = await submit_with_retry(session, user, draft_id, body.remark)
    return {"order_id": order.id, "order_no": order.order_no, "status": order.status, "created": created}
