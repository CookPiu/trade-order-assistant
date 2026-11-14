"""主数据维护（FR-050、US6）：合同台账、物料编码字典与别名的新增、修改、查询，仅系统管理员可用。

不提供删除和批量导入。管理员维护全部部门的合同，合同按所属部门隔离给经办人和审批人使用。
"""
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import BizError
from app.core.security import require_roles
from app.models import ROLE_ADMIN, Contract, ContractItem, Dept, Material, MaterialAlias, Party, Project, User
from app.services import audit, quota
from app.services.material_normalizer import clean

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin = require_roles(ROLE_ADMIN)

PARTY_KIND = {"sales": "customer", "purchase": "supplier"}


def _strip(v: str) -> str:
    return (v or "").strip()


# ---------- 下拉选项 ----------


@router.get("/options")
async def options(_: User = Depends(admin), session: AsyncSession = Depends(get_session)):
    """合同表单的部门、签约单位、工程项目选项。"""
    depts = (await session.execute(select(Dept).order_by(Dept.id))).scalars().all()
    parties = (await session.execute(select(Party).order_by(Party.name))).scalars().all()
    projects = (await session.execute(select(Project).order_by(Project.name))).scalars().all()
    return {
        "depts": [{"id": d.id, "code": d.code, "name": d.name} for d in depts],
        "parties": [{"id": p.id, "name": p.name, "kind": p.kind} for p in parties],
        "projects": [
            {"id": p.id, "name": p.name, "address": p.address, "contact": p.contact, "phone": p.phone}
            for p in projects
        ],
    }


# ---------- 合同台账 ----------


class ContractItemIn(BaseModel):
    material_code: str
    unit_price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)


class ContractIn(BaseModel):
    contract_no: str = Field(min_length=1, max_length=32)
    contract_type: Literal["sales", "purchase"]
    dept_id: int
    party_name: str = Field(min_length=1, max_length=128)
    project_name: str = Field(min_length=1, max_length=128)
    address: str = Field(min_length=1, max_length=255)
    contact: str = Field(min_length=1, max_length=32)
    phone: str = Field("", max_length=32)
    total_amount: Decimal = Field(gt=0)
    total_qty: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=8)
    sign_date: date
    expire_date: date
    items: list[ContractItemIn] = Field(min_length=1)

    @field_validator("contract_no", "party_name", "project_name", "address", "contact", "phone", "unit")
    @classmethod
    def _trim(cls, v: str) -> str:
        return _strip(v)

    @model_validator(mode="after")
    def _check(self):
        if self.expire_date < self.sign_date:
            raise ValueError("到期日期不能早于签订日期")
        codes = [i.material_code.strip() for i in self.items]
        if len(set(codes)) != len(codes):
            raise ValueError("合同明细中物料编码重复")
        return self


def contract_view(c: Contract) -> dict:
    return {
        "id": c.id,
        "contract_no": c.contract_no,
        "contract_type": c.contract_type,
        "dept_id": c.dept_id,
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
        "version": c.version,
        "updated_at": c.updated_at,
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
    }


@router.get("/contracts")
async def list_contracts(
    q: str | None = None,
    contract_type: Literal["sales", "purchase"] | None = None,
    dept_id: int | None = None,
    _: User = Depends(admin),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Contract).join(Party, Contract.party_id == Party.id).order_by(Contract.contract_no)
    if contract_type:
        stmt = stmt.where(Contract.contract_type == contract_type)
    if dept_id:
        stmt = stmt.where(Contract.dept_id == dept_id)
    if q and q.strip():
        k = q.strip()
        stmt = stmt.where(or_(Contract.contract_no.contains(k), Party.name.contains(k)))
    rows = (await session.execute(stmt)).unique().scalars().all()
    out = []
    for c in rows:
        used = await quota.contract_usage(session, c.id)
        out.append({**contract_view(c), "used_amount": used.amount, "remaining_amount": c.total_amount - used.amount})
    return out


async def _party(session: AsyncSession, name: str, contract_type: str) -> Party:
    p = (await session.execute(select(Party).where(Party.name == name))).scalar_one_or_none()
    if p is None:
        p = Party(name=name, kind=PARTY_KIND[contract_type])
        session.add(p)
        await session.flush()
    return p


async def _project(session: AsyncSession, body: ContractIn) -> Project:
    p = (await session.execute(select(Project).where(Project.name == body.project_name))).scalar_one_or_none()
    if p is None:
        p = Project(name=body.project_name, address=body.address, contact=body.contact, phone=body.phone)
        session.add(p)
        await session.flush()
    else:
        p.address, p.contact, p.phone = body.address, body.contact, body.phone
    return p


async def _check_refs(session: AsyncSession, body: ContractIn) -> None:
    if await session.get(Dept, body.dept_id) is None:
        raise BizError(422, "所属部门不存在")
    codes = [i.material_code.strip() for i in body.items]
    found = set((await session.execute(select(Material.code).where(Material.code.in_(codes)))).scalars().all())
    missing = [c for c in codes if c not in found]
    if missing:
        # 合同明细的物料编码只能来自物料字典（C-002）
        raise BizError(422, f"物料编码不在物料字典中：{'、'.join(missing)}")


async def _load_contract(session: AsyncSession, contract_id: int, *, lock: bool = False) -> Contract:
    stmt = select(Contract).where(Contract.id == contract_id)
    if lock:
        # 与提交时的合同行锁互斥，避免额度核验读到修改一半的合同
        stmt = stmt.with_for_update(of=Contract)
    c = (await session.execute(stmt)).unique().scalar_one_or_none()
    if c is None:
        raise BizError(404, "合同不存在")
    return c


@router.get("/contracts/{contract_id}")
async def get_contract(contract_id: int, _: User = Depends(admin), session: AsyncSession = Depends(get_session)):
    return contract_view(await _load_contract(session, contract_id))


@router.post("/contracts")
async def create_contract(body: ContractIn, user: User = Depends(admin), session: AsyncSession = Depends(get_session)):
    exists = (
        await session.execute(select(Contract.id).where(Contract.contract_no == body.contract_no))
    ).scalar_one_or_none()
    if exists is not None:
        raise BizError(409, f"合同号 {body.contract_no} 已存在")
    await _check_refs(session, body)
    party = await _party(session, body.party_name, body.contract_type)
    project = await _project(session, body)
    c = Contract(
        contract_no=body.contract_no,
        contract_type=body.contract_type,
        party_id=party.id,
        project_id=project.id,
        dept_id=body.dept_id,
        total_amount=body.total_amount,
        total_qty=body.total_qty,
        unit=body.unit,
        sign_date=body.sign_date,
        expire_date=body.expire_date,
        version=0,
    )
    session.add(c)
    await session.flush()
    for i in body.items:
        session.add(
            ContractItem(
                contract_id=c.id, material_code=i.material_code.strip(), unit_price=i.unit_price, quantity=i.quantity
            )
        )
    audit.record(
        session, user, audit.MASTER_UPDATE,
        detail={"entity": "contract", "op": "create", "key": c.contract_no, "after": body.model_dump(mode="json")},
    )
    await session.commit()
    session.expunge_all()
    return contract_view(await _load_contract(session, c.id))


@router.put("/contracts/{contract_id}")
async def update_contract(
    contract_id: int, body: ContractIn, user: User = Depends(admin), session: AsyncSession = Depends(get_session)
):
    c = await _load_contract(session, contract_id, lock=True)
    if body.contract_no != c.contract_no:
        dup = (
            await session.execute(select(Contract.id).where(Contract.contract_no == body.contract_no))
        ).scalar_one_or_none()
        if dup is not None:
            raise BizError(409, f"合同号 {body.contract_no} 已存在")
    await _check_refs(session, body)
    before = contract_view(c)
    party = await _party(session, body.party_name, body.contract_type)
    project = await _project(session, body)
    c.contract_no = body.contract_no
    c.contract_type = body.contract_type
    c.party_id, c.project_id, c.dept_id = party.id, project.id, body.dept_id
    c.total_amount, c.total_qty, c.unit = body.total_amount, body.total_qty, body.unit
    c.sign_date, c.expire_date = body.sign_date, body.expire_date
    c.version = (c.version or 0) + 1

    # 明细按物料编码对齐：保留的更新，新增的插入，去掉的删除
    wanted = {i.material_code.strip(): i for i in body.items}
    for item in list(c.items):
        if item.material_code in wanted:
            src = wanted.pop(item.material_code)
            item.unit_price, item.quantity = src.unit_price, src.quantity
        else:
            await session.delete(item)
    for code, src in wanted.items():
        session.add(ContractItem(contract_id=c.id, material_code=code, unit_price=src.unit_price, quantity=src.quantity))
    audit.record(
        session, user, audit.MASTER_UPDATE,
        detail={
            "entity": "contract", "op": "update", "key": body.contract_no,
            "before": _jsonable(before), "after": body.model_dump(mode="json"),
        },
    )
    await session.commit()
    session.expunge_all()
    return contract_view(await _load_contract(session, contract_id))


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items() if k != "updated_at"}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, (Decimal, date)):
        return str(v)
    return v


# ---------- 物料字典 ----------


class MaterialIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    spec: str = Field("", max_length=64)
    unit: str = Field(min_length=1, max_length=8)
    brand: str = Field("", max_length=64)
    category: str = Field("", max_length=32)
    fair_price: Decimal | None = Field(None, gt=0)

    @field_validator("code", "name", "spec", "unit", "brand", "category")
    @classmethod
    def _trim(cls, v: str) -> str:
        return _strip(v)


def material_view(m: Material, aliases: list[str]) -> dict:
    return {
        "code": m.code, "name": m.name, "spec": m.spec, "unit": m.unit, "brand": m.brand,
        "category": m.category, "fair_price": m.fair_price, "aliases": aliases,
    }


async def _aliases_of(session: AsyncSession, codes: list[str]) -> dict[str, list[str]]:
    rows = (
        await session.execute(
            select(MaterialAlias.material_code, MaterialAlias.alias)
            .where(MaterialAlias.material_code.in_(codes))
            .order_by(MaterialAlias.id)
        )
    ).all()
    out: dict[str, list[str]] = {}
    for code, alias in rows:
        out.setdefault(code, []).append(alias)
    return out


@router.get("/materials")
async def list_materials(
    q: str | None = None, _: User = Depends(admin), session: AsyncSession = Depends(get_session)
):
    stmt = select(Material).order_by(Material.code)
    if q and q.strip():
        k = q.strip()
        alias_codes = select(MaterialAlias.material_code).where(MaterialAlias.alias.contains(k))
        stmt = stmt.where(
            or_(Material.code.contains(k), Material.name.contains(k), Material.spec.contains(k),
                Material.code.in_(alias_codes))
        )
    rows = (await session.execute(stmt)).scalars().all()
    aliases = await _aliases_of(session, [m.code for m in rows])
    return [material_view(m, aliases.get(m.code, [])) for m in rows]


def _material_dump(m: Material) -> dict:
    return _jsonable(material_view(m, []) | {"aliases": None})


@router.post("/materials")
async def create_material(body: MaterialIn, user: User = Depends(admin), session: AsyncSession = Depends(get_session)):
    code = body.code.upper()
    if await session.get(Material, code) is not None:
        raise BizError(409, f"物料编码 {code} 已存在")
    m = Material(**body.model_dump(exclude={"code"}), code=code)
    session.add(m)
    audit.record(
        session, user, audit.MASTER_UPDATE,
        detail={"entity": "material", "op": "create", "key": code, "after": _material_dump(m)},
    )
    await session.commit()
    return material_view(m, [])


@router.put("/materials/{code}")
async def update_material(
    code: str, body: MaterialIn, user: User = Depends(admin), session: AsyncSession = Depends(get_session)
):
    m = await session.get(Material, code)
    if m is None:
        raise BizError(404, "物料不存在")
    if body.code.upper() != code:
        # 编码被合同、订单引用，只能新增不能改名
        raise BizError(422, "物料编码不能修改")
    before = _material_dump(m)
    for k, v in body.model_dump(exclude={"code"}).items():
        setattr(m, k, v)
    audit.record(
        session, user, audit.MASTER_UPDATE,
        detail={"entity": "material", "op": "update", "key": code, "before": before, "after": _material_dump(m)},
    )
    await session.commit()
    aliases = await _aliases_of(session, [code])
    return material_view(m, aliases.get(code, []))


# ---------- 物料别名 ----------


class AliasIn(BaseModel):
    alias: str = Field(min_length=1, max_length=64)
    material_code: str = Field(min_length=1, max_length=32)

    @field_validator("alias", "material_code")
    @classmethod
    def _trim(cls, v: str) -> str:
        return _strip(v)


def alias_view(a: MaterialAlias, m: Material | None) -> dict:
    return {
        "id": a.id, "alias": a.alias, "material_code": a.material_code,
        "material_name": m.name if m else "", "spec": m.spec if m else "",
    }


async def _check_alias(session: AsyncSession, body: AliasIn, self_id: int | None = None) -> Material:
    m = await session.get(Material, body.material_code.upper())
    if m is None:
        raise BizError(422, f"物料编码 {body.material_code} 不在物料字典中")
    key = clean(body.alias)
    if not key:
        raise BizError(422, "别名不能只包含空格和符号")
    # 标准化时按去空格、去符号后的文本匹配，这里按同样规则查重
    for a in (await session.execute(select(MaterialAlias))).scalars().all():
        if a.id != self_id and clean(a.alias) == key:
            raise BizError(409, f"别名“{body.alias}”与已有别名“{a.alias}”重复（{a.material_code}）")
    return m


@router.get("/aliases")
async def list_aliases(
    q: str | None = None,
    material_code: str | None = None,
    _: User = Depends(admin),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(MaterialAlias, Material).join(Material, Material.code == MaterialAlias.material_code)
    if material_code:
        stmt = stmt.where(MaterialAlias.material_code == material_code)
    if q and q.strip():
        k = q.strip()
        stmt = stmt.where(or_(MaterialAlias.alias.contains(k), MaterialAlias.material_code.contains(k), Material.name.contains(k)))
    rows = (await session.execute(stmt.order_by(MaterialAlias.material_code, MaterialAlias.id))).all()
    return [alias_view(a, m) for a, m in rows]


@router.post("/aliases")
async def create_alias(body: AliasIn, user: User = Depends(admin), session: AsyncSession = Depends(get_session)):
    m = await _check_alias(session, body)
    a = MaterialAlias(alias=body.alias, material_code=m.code)
    session.add(a)
    await session.flush()
    audit.record(
        session, user, audit.MASTER_UPDATE,
        detail={"entity": "alias", "op": "create", "key": body.alias, "after": {"material_code": m.code}},
    )
    await session.commit()
    return alias_view(a, m)


@router.put("/aliases/{alias_id}")
async def update_alias(
    alias_id: int, body: AliasIn, user: User = Depends(admin), session: AsyncSession = Depends(get_session)
):
    a = await session.get(MaterialAlias, alias_id)
    if a is None:
        raise BizError(404, "别名不存在")
    m = await _check_alias(session, body, self_id=alias_id)
    before = {"alias": a.alias, "material_code": a.material_code}
    a.alias, a.material_code = body.alias, m.code
    audit.record(
        session, user, audit.MASTER_UPDATE,
        detail={"entity": "alias", "op": "update", "key": body.alias, "before": before,
                "after": {"alias": a.alias, "material_code": a.material_code}},
    )
    await session.commit()
    return alias_view(a, m)

