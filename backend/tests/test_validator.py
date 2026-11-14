"""草稿校验规则（FR-016、FR-020、FR-023、FR-024、C-002、D-012）。"""
from datetime import timedelta
from decimal import Decimal

from app.core import clock
from app.models import PENDING_CONFIRM
from app.schemas import DraftData, DraftItem
from app.services.draft_validator import assemble
from tests.conftest import get_user


def _fields(a, level="error"):
    return {i.field for i in a.issues if i.level == level}


async def test_scenario_one_fills_contract_and_fixed_attrs(db):
    async with db() as s:
        user = await get_user(s, "jbr01")
        a = await assemble(
            s,
            user,
            DraftData(
                order_type="sales",
                contract_no="2026-WZ-089",
                delivery_date=clock.today() + timedelta(days=2),
                items=[DraftItem(raw_name="HRB400E 螺纹钢", material_code="STL-RB-400E-20", quantity=Decimal("200"))],
            ),
        )
    assert a.errors == []
    assert a.data.party_name == "中建八局第三建设有限公司"
    assert a.data.project_name == "科技城项目"
    assert (a.data.biz_name, a.data.purchase_mode, a.data.biz_tag) == ("国内传统贸易", "直发", "传统贸易")
    assert a.data.operator_name == "张经办"
    assert a.data.items[0].unit_price == Decimal("3650")
    assert a.quota is not None and a.quota.over_quota is False


async def test_missing_contract_and_unknown_material(db):
    async with db() as s:
        user = await get_user(s, "jbr01")
        a = await assemble(
            s,
            user,
            DraftData(order_type="sales", items=[DraftItem(material_code="FAKE-001", quantity=Decimal("1"))]),
        )
    assert a.status == PENDING_CONFIRM
    assert {"contract_no", "delivery_date", "items.0.material_code"} <= _fields(a)
    assert a.data.items[0].material_code is None  # 字典外编码被清空


async def test_type_mismatch_and_other_dept(db):
    async with db() as s:
        user = await get_user(s, "jbr01")
        mismatch = await assemble(s, user, DraftData(order_type="purchase", contract_no="2026-WZ-089"))
        other = await assemble(s, user, DraftData(order_type="sales", contract_no="2026-JC-012"))
    assert any("销售合同" in i.message for i in mismatch.errors)
    assert any("不属于本部门" in i.message for i in other.errors)
    assert other.data.party_name == ""  # 不泄露其他部门合同信息


async def test_delivery_date_rules(db):
    async with db() as s:
        user = await get_user(s, "jbr01")
        past = await assemble(s, user, DraftData(order_type="sales", contract_no="2026-WZ-095", delivery_date=clock.today() - timedelta(days=1)))
        late = await assemble(s, user, DraftData(order_type="sales", contract_no="2026-WZ-095", delivery_date=clock.today() + timedelta(days=30)))
    assert any("早于今天" in i.message for i in past.errors)
    assert any("晚于合同到期日" in i.message for i in late.errors)


async def test_fair_price_and_material_outside_contract(db):
    async with db() as s:
        user = await get_user(s, "jbr01")
        a = await assemble(
            s,
            user,
            DraftData(
                order_type="sales",
                contract_no="2026-WZ-089",
                delivery_date=clock.today() + timedelta(days=3),
                items=[
                    DraftItem(material_code="STL-RB-400E-20", quantity=Decimal("10"), unit_price=Decimal("4500")),
                    DraftItem(material_code="CEM-PO-425", quantity=Decimal("10"), unit_price=Decimal("430")),
                ],
            ),
        )
    assert "items.0.unit_price" in _fields(a, "warning")
    assert any("不在合同" in i.message for i in a.errors if i.field == "items.1.material_code")
