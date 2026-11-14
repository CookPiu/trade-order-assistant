"""审计日志查询（FR-052、US6）：按操作人、动作、时间筛选，仅系统管理员可用。"""
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import require_roles
from app.models import ROLE_ADMIN, AuditLog, User
from app.services import audit

router = APIRouter(prefix="/api/audit", tags=["audit"])
admin = require_roles(ROLE_ADMIN)

ACTIONS = [
    audit.LOGIN, audit.CHAT, audit.DRAFT_SAVE, audit.IMAGE_RECOGNIZE, audit.EXCEL_IMPORT, audit.SUBMIT,
    audit.RESUBMIT, audit.APPROVE, audit.RETURN, audit.REJECT, audit.MASTER_UPDATE, audit.PARAM_UPDATE,
]


class AuditRow(BaseModel):
    id: int
    created_at: datetime | None
    username: str
    display_name: str
    action: str
    order_no: str
    input_text: str
    input_hash: str
    detail: dict[str, Any]


class AuditPage(BaseModel):
    total: int
    items: list[AuditRow]


@router.get("/options")
async def options(_: User = Depends(admin), session: AsyncSession = Depends(get_session)):
    users = (await session.execute(select(User).order_by(User.id))).unique().scalars().all()
    return {
        "actions": ACTIONS,
        "users": [{"username": u.username, "display_name": u.display_name, "role": u.role} for u in users],
    }


@router.get("", response_model=AuditPage)
async def list_audit(
    username: str | None = None,
    action: str | None = Query(None, description="逗号分隔的动作"),
    date_from: date | None = None,
    date_to: date | None = None,
    order_no: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(admin),
    session: AsyncSession = Depends(get_session),
):
    conds = []
    if username and username.strip():
        conds.append(AuditLog.username == username.strip())
    wanted = [a for a in (action or "").split(",") if a in ACTIONS]
    if wanted:
        conds.append(AuditLog.action.in_(wanted))
    if date_from:
        conds.append(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        conds.append(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    if order_no and order_no.strip():
        conds.append(AuditLog.order_no.contains(order_no.strip()))
    total = (await session.execute(select(func.count()).select_from(AuditLog).where(*conds))).scalar_one()
    rows = (
        await session.execute(
            select(AuditLog, User.display_name)
            .outerjoin(User, User.id == AuditLog.user_id)
            .where(*conds)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AuditPage(
        total=total,
        items=[
            AuditRow(
                id=a.id, created_at=a.created_at, username=a.username, display_name=name or "",
                action=a.action, order_no=a.order_no, input_text=a.input_text, input_hash=a.input_hash,
                detail=a.detail or {},
            )
            for a, name in rows
        ],
    )
