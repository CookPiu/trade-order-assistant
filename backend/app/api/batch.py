"""Excel 批量提单与导入记录（FR-017、FR-036、FR-047、US3）。"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.core.db import get_session, session_factory
from app.core.errors import BizError
from app.core.security import require_roles
from app.models import ROLE_OPERATOR, ImportBatch, ImportRow, User
from app.services import audit, batch_submit, excel_parser

router = APIRouter(prefix="/api/batch", tags=["batch"])
operator = require_roles(ROLE_OPERATOR)

MAX_BYTES = 5 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def get_maker() -> async_sessionmaker[AsyncSession]:
    """批量提交每行使用独立会话；测试中可覆盖为测试库。"""
    return session_factory()


class RowInput(BaseModel):
    order_type: str = ""
    contract_no: str = ""
    raw_name: str = ""
    spec: str = ""
    quantity: str = ""
    unit_price: str = ""
    delivery_date: str = ""
    remark: str = ""
    material_code: str = ""


class RowView(BaseModel):
    id: int
    row_no: int
    input: dict[str, Any]
    result: dict[str, Any]
    status: str
    issues: list[dict[str, Any]]
    order_no: str | None
    message: str


class BatchSummary(BaseModel):
    id: int
    file_name: str
    created_at: datetime | None
    total_rows: int
    success_rows: int
    failed_rows: int
    status: str


class BatchView(BatchSummary):
    rows: list[RowView]


def _summary(b: ImportBatch) -> dict[str, Any]:
    return {
        "id": b.id,
        "file_name": b.file_name,
        "created_at": b.created_at,
        "total_rows": b.total_rows,
        "success_rows": b.success_rows,
        "failed_rows": b.failed_rows,
        "status": b.status,
    }


def _view(b: ImportBatch) -> BatchView:
    rows = []
    for r in sorted(b.rows, key=lambda x: x.row_no):
        result = {k: v for k, v in (r.data.get("result") or {}).items() if k != "draft"}
        rows.append(
            RowView(
                id=r.id,
                row_no=r.row_no,
                input=r.data.get("input") or {},
                result=result,
                status=r.status,
                issues=r.issues or [],
                order_no=r.order_no,
                message=r.message,
            )
        )
    return BatchView(**_summary(b), rows=rows)


async def _load(session: AsyncSession, user: User, batch_id: int) -> ImportBatch:
    batch = await session.get(ImportBatch, batch_id)
    if batch is None or batch.user_id != user.id:
        raise BizError(404, "导入批次不存在")
    return batch


@router.get("/template")
async def template(_: User = Depends(operator)):
    return Response(
        content=excel_parser.template_bytes(),
        media_type=XLSX,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E6%89%B9%E9%87%8F%E6%8F%90%E5%8D%95%E6%A8%A1%E6%9D%BF.xlsx"},
    )


@router.post("", response_model=BatchView)
async def upload(
    file: UploadFile = File(...), user: User = Depends(operator), session: AsyncSession = Depends(get_session)
):
    name = file.filename or "导入.xlsx"
    if not name.lower().endswith(".xlsx"):
        raise BizError(400, "只支持 .xlsx 格式的 Excel 文件")
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise BizError(400, "文件超过 5 MB")
    parsed = excel_parser.parse(content)
    batch = ImportBatch(file_name=name[:255], user_id=user.id, dept_id=user.dept_id, status="parsed")
    batch.rows = [
        ImportRow(row_no=row_no, data={"input": inp}, issues=[], status="error", message="") for row_no, inp in parsed
    ]
    session.add(batch)
    await excel_parser.validate_batch(session, user, batch, today=clock.today())
    audit.record(
        session,
        user,
        audit.EXCEL_IMPORT,
        input_hash=audit.sha256_hex(content),
        detail={"file_name": name, "rows": len(parsed)},
    )
    await session.commit()
    await session.refresh(batch)
    return _view(batch)


@router.get("", response_model=list[BatchSummary])
async def list_batches(user: User = Depends(operator), session: AsyncSession = Depends(get_session)):
    stmt = select(ImportBatch).where(ImportBatch.user_id == user.id).order_by(ImportBatch.id.desc()).limit(50)
    return [_summary(b) for b in (await session.execute(stmt)).scalars().all()]


@router.get("/{batch_id}", response_model=BatchView)
async def get_batch(batch_id: int, user: User = Depends(operator), session: AsyncSession = Depends(get_session)):
    return _view(await _load(session, user, batch_id))


@router.put("/{batch_id}/rows/{row_id}", response_model=BatchView)
async def update_row(
    batch_id: int,
    row_id: int,
    body: RowInput,
    user: User = Depends(operator),
    session: AsyncSession = Depends(get_session),
):
    """行内修改后重新校验；同一合同后续行的累计额度随之变化，因此整批重算。"""
    batch = await _load(session, user, batch_id)
    row = next((r for r in batch.rows if r.id == row_id), None)
    if row is None:
        raise BizError(404, "导入行不存在")
    if row.status == "submitted":
        raise BizError(409, "该行已提交，不能修改")
    row.data = {**row.data, "input": body.model_dump()}
    await excel_parser.validate_batch(session, user, batch, today=clock.today())
    await session.commit()
    return _view(batch)


@router.post("/{batch_id}/submit", response_model=BatchView)
async def submit_batch(
    batch_id: int,
    user: User = Depends(operator),
    session: AsyncSession = Depends(get_session),
    maker: async_sessionmaker[AsyncSession] = Depends(get_maker),
):
    batch = await _load(session, user, batch_id)
    await excel_parser.validate_batch(session, user, batch, today=clock.today())
    await session.commit()
    if not any(r.status in batch_submit.SUBMITTABLE for r in batch.rows):
        raise BizError(422, "没有可提交的行，请先修正异常行")

    outcomes = await batch_submit.submit_rows(maker, user.id, batch)
    for row in batch.rows:
        out = outcomes.get(row.id)
        if out is None:
            continue
        if out.ok:
            row.status = "submitted"
            row.order_no = out.order_no
            row.message = "超额，已转待特批" if out.order_status == "pending_special" else ""
        else:
            row.status = "failed"
            row.message = out.message
    excel_parser.refresh_counts(batch)
    batch.status = "submitted"
    await session.commit()
    return _view(batch)
