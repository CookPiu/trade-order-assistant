"""草稿装配与校验：补全合同与固定属性、核对物料字典、计算额度、生成待确认与提醒列表。

对话、图片识别、Excel 导入和正式提交共用这一套规则。
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models import DRAFT, PENDING_CONFIRM, Contract, Material, User
from app.schemas import DraftData, Issue, QuotaSummary
from app.services import params, quota

CENT = Decimal("0.01")
TYPE_LABEL = {"sales": "销售", "purchase": "采购"}


@dataclass
class Assembled:
    data: DraftData
    issues: list[Issue]
    status: str
    contract: Contract | None
    quota: quota.QuotaResult | None

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    def quota_summary(self) -> QuotaSummary | None:
        if self.quota is None or self.contract is None:
            return None
        q = self.quota
        return QuotaSummary(
            contract_no=self.contract.contract_no,
            unit=self.contract.unit,
            total_amount=q.total_amount,
            used_amount=q.used_amount,
            remaining_amount=q.remaining_amount,
            total_qty=q.total_qty,
            used_qty=q.used_qty,
            remaining_qty=q.remaining_qty,
            current_amount=q.current_amount,
            current_qty=q.current_qty,
            after_remaining_amount=q.after_remaining_amount,
            over_quota=q.over_quota,
            low_quota=q.low_quota,
        )


async def find_contract(session: AsyncSession, contract_no: str, *, for_update: bool = False) -> Contract | None:
    stmt = select(Contract).where(Contract.contract_no == contract_no.strip())
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).unique().scalar_one_or_none()


async def assemble(
    session: AsyncSession,
    user: User,
    data: DraftData,
    *,
    today: date | None = None,
    fill_price_from_contract: bool = True,
    exclude_order_id: int | None = None,
    extra_usage: quota.Usage | None = None,
    contract: Contract | None = None,
) -> Assembled:
    """补全并校验草稿。

    extra_usage：Excel 批量时同一批前面行已占用的额度（DESIGN 4.3）。
    contract：调用方已加锁读取的合同，提交事务中传入以避免二次查询。
    """
    today = today or clock.today()
    data = data.model_copy(deep=True)
    issues: list[Issue] = []

    def err(field: str, msg: str) -> None:
        issues.append(Issue(field=field, level="error", message=msg))

    def warn(field: str, msg: str) -> None:
        issues.append(Issue(field=field, level="warning", message=msg))

    # 固定业务属性与身份绑定（FR-013、FR-014）
    fixed = await params.get_param(session, "fixed_attrs")
    data.biz_name = fixed["biz_name"]
    data.purchase_mode = fixed["purchase_mode"]
    data.biz_tag = fixed["biz_tag"]
    data.operator_name = data.operator_name or user.display_name
    data.creator_name = data.creator_name or user.display_name
    data.dept_name = user.dept.name
    data.created_at = data.created_at or clock.now().strftime("%Y-%m-%d %H:%M:%S")

    # 合同关联（FR-020、FR-024）
    if contract is None and data.contract_no:
        contract = await find_contract(session, data.contract_no)
    if not data.contract_no:
        err("contract_no", "缺少合同编号")
        contract = None
    elif contract is None or contract.dept_id != user.dept_id:
        err("contract_no", f"合同 {data.contract_no} 不存在或不属于本部门")
        contract = None
    elif contract.contract_type != data.order_type:
        err(
            "contract_no",
            f"合同 {contract.contract_no} 是{TYPE_LABEL[contract.contract_type]}合同，不能用于{TYPE_LABEL[data.order_type]}订单",
        )
    if contract is not None:
        data.contract_no = contract.contract_no
        data.party_name = contract.party.name
        data.project_name = contract.project.name
        data.address = data.address or contract.project.address
        data.contact = data.contact or f"{contract.project.contact} {contract.project.phone}".strip()

    # 交期（FR-023、D-012）
    if data.delivery_date is None:
        err("delivery_date", "缺少交期")
    elif data.delivery_date < today:
        err("delivery_date", f"交期 {data.delivery_date} 早于今天")
    elif contract is not None and data.delivery_date > contract.expire_date:
        err("delivery_date", f"交期 {data.delivery_date} 晚于合同到期日 {contract.expire_date}")

    if not data.address:
        err("address", "缺少收货地址")

    # 物资明细（FR-016、C-002）
    if not data.items:
        err("items", "缺少物资明细")
    contract_items = {ci.material_code: ci for ci in contract.items} if contract else {}
    deviation = await params.get_param(session, "fair_price_deviation")
    total_amount = Decimal("0")
    total_qty = Decimal("0")
    for idx, item in enumerate(data.items):
        prefix = f"items.{idx}"
        material: Material | None = None
        if item.material_code:
            material = await session.get(Material, item.material_code)
            if material is None:
                # 字典外编码一律清空，不允许保留（C-002）
                err(f"{prefix}.material_code", f"物料编码 {item.material_code} 不在物料字典中")
                item.material_code = None
        if material is None:
            if not any(i.field == f"{prefix}.material_code" for i in issues):
                label = item.raw_name or item.material_name or "该物资"
                tip = "，请从候选中选择" if item.candidates else ""
                err(f"{prefix}.material_code", f"“{label}”未匹配到标准物料{tip}")
        else:
            item.material_name = material.name
            item.spec = material.spec
            item.unit = material.unit
            item.candidates = []
            if contract is not None and material.code not in contract_items:
                err(f"{prefix}.material_code", f"{material.name} {material.spec} 不在合同 {contract.contract_no} 的物料范围内")

        if item.quantity is None or item.quantity <= 0:
            err(f"{prefix}.quantity", "数量缺失或不大于 0")

        if item.unit_price is None and item.amount is not None and item.quantity:
            item.unit_price = (item.amount / item.quantity).quantize(CENT, ROUND_HALF_UP)
        if item.unit_price is None and fill_price_from_contract and material is not None and material.code in contract_items:
            item.unit_price = contract_items[material.code].unit_price
            issues.append(Issue(field=f"{prefix}.unit_price", level="info", message="单价取自合同约定单价"))
        if item.unit_price is None or item.unit_price <= 0:
            err(f"{prefix}.unit_price", "缺少含税单价")
        elif material is not None and quota.fair_price_deviates(item.unit_price, material.fair_price, deviation):
            warn(
                f"{prefix}.unit_price",
                f"单价 {item.unit_price} 偏离公允价 {material.fair_price} 超过 {deviation:.0%}",
            )

        if item.quantity and item.unit_price:
            item.amount = (item.quantity * item.unit_price).quantize(CENT, ROUND_HALF_UP)
            total_amount += item.amount
            total_qty += item.quantity

    # 额度（FR-021、FR-022、FR-025、FR-028）
    qres: quota.QuotaResult | None = None
    if contract is not None:
        usage = await quota.contract_usage(session, contract.id, exclude_order_id)
        if extra_usage is not None:
            usage = quota.Usage(usage.amount + extra_usage.amount, usage.qty + extra_usage.qty)
        warn_ratio = await params.get_param(session, "quota_warn_ratio")
        qres = quota.evaluate(contract.total_amount, contract.total_qty, usage, total_amount, total_qty, warn_ratio)
        if qres.over_quota:
            issues.append(
                Issue(
                    field="quota",
                    level="over",
                    message=f"本次金额 {total_amount} 超出合同剩余可下金额 {qres.remaining_amount}，提交需填写备注并转待特批",
                )
            )
        if qres.qty_exceeded:
            warn("quota.qty", f"本次数量 {total_qty} 超出合同剩余可下数量 {qres.remaining_qty} {contract.unit}")
        if qres.low_quota:
            warn("quota.low", f"提交后合同剩余金额 {qres.after_remaining_amount}，低于配额阈值 {warn_ratio:.0%}")

    status = PENDING_CONFIRM if any(i.level == "error" for i in issues) else DRAFT
    return Assembled(data=data, issues=issues, status=status, contract=contract, quota=qres)
