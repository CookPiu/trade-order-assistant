"""提交事务：幂等防重（SC-004）与并发额度占用（SC-003）。"""
import asyncio
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core import clock
from app.api.drafts import submit_with_retry
from app.models import PENDING_SPECIAL, SUBMITTED, Order, TradeSalesOrder
from app.schemas import DraftData, DraftItem
from app.services import drafts
from tests.conftest import get_user


def _data(contract_no: str, order_type: str, code: str, qty: str, price: str | None = None, remark: str = "") -> DraftData:
    return DraftData(
        order_type=order_type,
        contract_no=contract_no,
        delivery_date=clock.today() + timedelta(days=2),
        remark=remark,
        items=[DraftItem(material_code=code, quantity=Decimal(qty), unit_price=Decimal(price) if price else None)],
    )


async def _new_draft(maker, username: str, data: DraftData) -> str:
    async with maker() as s:
        user = await get_user(s, username)
        draft, _ = await drafts.save(s, user, data, draft_id=None, session_id="t")
        await s.commit()
        return draft.id


async def _submit(maker, username: str, draft_id: str, remark: str = ""):
    async with maker() as s:
        user = await get_user(s, username)
        order, created = await submit_with_retry(s, user, draft_id, remark)
        return order.order_no, order.status, created


async def test_repeat_submit_creates_one_order(db):
    draft_id = await _new_draft(db, "jbr01", _data("2026-WZ-089", "sales", "STL-RB-400E-20", "200"))
    results = await asyncio.gather(*[_submit(db, "jbr01", draft_id) for _ in range(5)])
    nos = {r[0] for r in results}
    assert len(nos) == 1
    assert sum(1 for r in results if r[2]) == 1
    no = nos.pop()
    assert no.startswith(f"XSDD-WZGS-{clock.today():%Y%m%d}-")
    async with db() as s:
        assert (await s.execute(select(func.count()).select_from(Order).where(Order.draft_id == draft_id))).scalar() == 1
        trade = (await s.execute(select(TradeSalesOrder).where(TradeSalesOrder.order_no == no))).scalar_one()
        assert trade.status == SUBMITTED
        order = (await s.execute(select(Order).where(Order.order_no == no))).scalar_one()
        # 单价取自合同约定单价 3650
        assert order.total_amount == Decimal("730000.00")


async def test_concurrent_submits_share_quota_correctly(db):
    # 2026-CG-031 剩余可下金额 150000；每笔 50 吨 × 440 = 22000，前 6 笔共 132000 未超额，之后每笔都超额
    ids = [
        await _new_draft(db, "jbr01", _data("2026-CG-031", "purchase", "CEM-PO-425", "50", "440", remark="并发测试"))
        for _ in range(10)
    ]
    results = await asyncio.gather(*[_submit(db, "jbr01", i) for i in ids])
    assert len({r[0] for r in results}) == 10
    async with db() as s:
        orders = (
            await s.execute(select(Order).where(Order.draft_id.in_(ids)).order_by(Order.order_no))
        ).scalars().all()
    # 按单号（即提交先后）累计，超额判定必须与逐笔计算一致
    remaining = Decimal("150000")
    for o in orders:
        expect_over = o.total_amount > remaining
        assert o.over_quota is expect_over, o.order_no
        assert o.status == (PENDING_SPECIAL if expect_over else SUBMITTED)
        remaining -= o.total_amount
    assert sum(1 for o in orders if not o.over_quota) == 6


async def test_over_quota_requires_remark(db):
    draft_id = await _new_draft(db, "jbr01", _data("2026-CG-031", "purchase", "CEM-PO-425", "500", "440"))
    try:
        await _submit(db, "jbr01", draft_id)
        raise AssertionError("超额未填备注不应提交成功")
    except Exception as e:  # noqa: BLE001
        assert "备注" in getattr(e, "message", str(e))
    no, status, _ = await _submit(db, "jbr01", draft_id, remark="项目追加采购")
    assert status == PENDING_SPECIAL
    assert no.startswith("CGDD-WZGS-")
