"""审计日志：只追加，随调用方事务一起提交。"""
import hashlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User

DRAFT_SAVE = "draft_save"
CHAT = "chat"
IMAGE_RECOGNIZE = "image_recognize"
EXCEL_IMPORT = "excel_import"
SUBMIT = "submit"
RESUBMIT = "resubmit"
APPROVE = "approve"
RETURN = "return"
REJECT = "reject"
LOGIN = "login"
MASTER_UPDATE = "master_update"
PARAM_UPDATE = "param_update"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record(
    session: AsyncSession,
    user: User | None,
    action: str,
    *,
    input_text: str = "",
    input_hash: str = "",
    order_no: str = "",
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "",
        action=action,
        input_text=input_text[:5000],
        input_hash=input_hash,
        order_no=order_no,
        detail=detail or {},
    )
    session.add(log)
    return log
