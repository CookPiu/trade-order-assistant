"""主数据查询（FR-020、FR-024），按部门隔离（FR-002）。"""
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import BizError
from app.core.security import get_current_user
from app.models import Contract, Material, User
from app.services import params, quota

router = APIRouter(prefix="/api/master", tags=["master"])


def contract_brief(c: Contract) -> dict:
    return {
        "id": c.id,
        "contract_no": c.contract_no,
        "contract_type": c.contract_type,
        "party_name": c.party.name,
        "project_name": c.project.name,
        "address": c.project.address,
        "contact": c.project.contact,
        "phone": c.project.phone,
        "total_amount": c.total_amount,
        "total_qty": c.total_qty,
        "unit": c.unit,
        "sign_date": c.sign_date,
        "expire_date": c.expire_date,
    }


async def quota_of(session: AsyncSession, c: Contract) -> dict:
    usage = await quota.contract_usage(session, c.id)
    ratio = await params.get_param(session, "quota_warn_ratio")
    r = quota.evaluate(c.total_amount, c.total_qty, usage, Decimal(0), Decimal(0), ratio)
    return {
        "total_amount": r.total_amount,
        "used_amount": r.used_amount,
        "remaining_amount": r.remaining_amount,
        "total_qty": r.total_qty,
        "used_qty": r.used_qty,
        "remaining_qty": r.remaining_qty,
        "unit": c.unit,
    }


@router.get("/contracts")
async def list_contracts(
    order_type: str | None = None,
    q: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Contract).where(Contract.dept_id == user.dept_id).order_by(Contract.contract_no)
    if order_type:
        stmt = stmt.where(Contract.contract_type == order_type)
    if q:
        stmt = stmt.where(Contract.contract_no.contains(q))
    rows = (await session.execute(stmt)).unique().scalars().all()
    return [contract_brief(c) for c in rows]


@router.get("/contracts/{contract_no}")
async def get_contract(
    contract_no: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    c = (
        await session.execute(select(Contract).where(Contract.contract_no == contract_no))
    ).unique().scalar_one_or_none()
    if c is None or c.dept_id != user.dept_id:
        raise BizError(404, "合同不存在")
    return {
        **contract_brief(c),
        "items": [
            {
                "material_code": i.material_code,
                "material_name": i.material.name,
                "spec": i.material.spec,
                "unit": i.material.unit,
                "unit_price": i.unit_price,
                "quantity": i.quantity,
            }
            for i in c.items
        ],
        "quota": await quota_of(session, c),
    }


@router.get("/materials")
async def list_materials(
    q: str | None = None, _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    stmt = select(Material).order_by(Material.code).limit(200)
    if q:
        stmt = stmt.where(or_(Material.code.contains(q), Material.name.contains(q), Material.spec.contains(q)))
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {"code": m.code, "name": m.name, "spec": m.spec, "unit": m.unit, "brand": m.brand, "fair_price": m.fair_price}
        for m in rows
    ]
