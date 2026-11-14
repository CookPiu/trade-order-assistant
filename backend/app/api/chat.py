"""对话提单接口（FR-010、FR-012、US1）。"""
import logging
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app import llm
from app.core.db import get_session
from app.core.security import require_roles
from app.graph.graph import build_graph
from app.graph.nodes import HELP_TEXT, TYPE_LABEL, llm_picker
from app.models import DRAFT_SUBMITTED, ROLE_OPERATOR, Draft, Order, User
from app.schemas import DraftData, DraftView
from app.services import audit, draft_validator, drafts

router = APIRouter(prefix="/api/chat", tags=["chat"])
operator = require_roles(ROLE_OPERATOR)
log = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    session_id: str
    draft_id: str | None = None
    message: str = ""
    action: Literal["new_sales", "new_purchase", "continue", "help"] | None = None


class ChatResponse(BaseModel):
    reply: str
    draft: DraftView | None = None
    failed: bool = False


async def _current(session: AsyncSession, user: User, draft_id: str | None) -> tuple[Draft | None, DraftData]:
    if draft_id:
        d = await drafts.load_own(session, user, draft_id)
        if d.status != DRAFT_SUBMITTED:
            return d, DraftData.model_validate(d.data)
    return None, DraftData()


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, user: User = Depends(operator), session: AsyncSession = Depends(get_session)):
    if body.action == "help":
        return ChatResponse(reply=HELP_TEXT)

    if body.action == "continue":
        d = await drafts.latest_open(session, user)
        if d is None:
            return ChatResponse(reply="没有未提交的草稿，可以直接描述新的订单。")
        view = await drafts.full_view(session, user, d)
        return ChatResponse(reply=f"已载入上次未提交的{TYPE_LABEL[view.data.order_type]}草稿，可以继续补充。", draft=view)

    if body.action in ("new_sales", "new_purchase"):
        order_type = "sales" if body.action == "new_sales" else "purchase"
        assembled = await draft_validator.assemble(session, user, DraftData(order_type=order_type))
        draft = await drafts.persist(session, user, assembled, draft_id=None, session_id=body.session_id)
        await session.commit()
        return ChatResponse(
            reply=f"已新建{TYPE_LABEL[order_type]}草稿，请告诉我合同号、物资、数量和交期。",
            draft=drafts.view_of(draft, assembled),
        )

    message = body.message.strip()
    if not message:
        return ChatResponse(reply="请输入提单描述。")
    current_draft, current = await _current(session, user, body.draft_id)
    draft_id = current_draft.id if current_draft else None
    order_id = current_draft.order_id if current_draft else None
    graph = build_graph()
    try:
        state = await graph.ainvoke(
            {"message": message, "today": clock.today(), "draft": current.model_dump(mode="json")},
            config={
                "configurable": {
                    "session": session,
                    "user": user,
                    "picker": llm_picker(session),
                    "exclude_order_id": order_id,
                }
            },
        )
    except llm.LLMError as e:
        # 模型失败时草稿保持不变，经办人可在预览区手工编辑（边界情况·模型失败）
        await session.rollback()
        view = await drafts.full_view(session, user, await drafts.load_own(session, user, draft_id)) if draft_id else None
        return ChatResponse(reply=f"{e}，草稿未改动。可以稍后重试，或直接在右侧编辑字段。", draft=view, failed=True)

    if state.get("assembled") is None:
        view = await drafts.full_view(session, user, await drafts.load_own(session, user, draft_id)) if draft_id else None
        return ChatResponse(reply=state["reply"], draft=view)

    assembled = state["assembled"]
    draft = await drafts.persist(session, user, assembled, draft_id=draft_id, session_id=body.session_id)
    audit.record(session, user, audit.CHAT, input_text=message, detail={"draft_id": draft.id})
    await session.commit()
    order = await session.get(Order, draft.order_id) if draft.order_id else None
    return ChatResponse(reply=state["reply"], draft=drafts.view_of(draft, assembled, order))
