"""审批与退回重提（FR-037、FR-038、D-009、D-010）。"""
from decimal import Decimal

from sqlalchemy import select

from app.models import AuditLog, TradePurchaseOrder
from tests._api import api_client
from tests.test_submit import _data, _new_draft, _submit


async def _order_id(c, order_no: str) -> int:
    r = await c.get("/api/orders", params={"order_type": "purchase"})
    return next(i["id"] for i in r.json()["items"] if i["order_no"] == order_no)


async def test_return_then_resubmit_keeps_number_and_excludes_own_usage(db):
    # 2026-CG-031 剩余 150000；本单 300 吨 × 440 = 132000
    draft_id = await _new_draft(db, "jbr01", _data("2026-CG-031", "purchase", "CEM-PO-425", "300", "440"))
    no, status, _ = await _submit(db, "jbr01", draft_id)
    assert status == "submitted"

    async with api_client(db, "spr01") as c:
        oid = await _order_id(c, no)
        r = await c.post(f"/api/orders/{oid}/return", json={"comment": ""})
        assert r.status_code == 422  # 退回必须填写意见
        r = await c.post(f"/api/orders/{oid}/return", json={"comment": "数量请核对到 320 吨"})
        assert r.status_code == 200 and r.json()["status"] == "returned"
        # 退回后审批人列表不再显示该单
        r = await c.get("/api/orders")
        assert no not in [i["order_no"] for i in r.json()["items"]]

    async with api_client(db, "jbr01") as c:
        r = await c.post(f"/api/orders/{oid}/edit")
        assert r.status_code == 200, r.text
        view = r.json()
        assert view["id"] == draft_id and view["status"] != "submitted"
        assert view["order_no"] == no and view["approval_comment"] == "数量请核对到 320 吨"
        # 剩余额度排除本单原占用：仍为 150000
        assert view["quota"]["remaining_amount"] == "150000.00"

        data = view["data"]
        data["items"][0]["quantity"] = "320"
        r = await c.post("/api/drafts", json={"session_id": "t", "draft_id": draft_id, "data": data})
        assert r.json()["quota"]["over_quota"] is False  # 140800 < 150000

        r = await c.post(f"/api/drafts/{draft_id}/submit", json={"remark": ""})
        body = r.json()
        assert body["order_no"] == no and body["status"] == "submitted" and body["created"] is True
        # 重复提交不再生成或修改
        r = await c.post(f"/api/drafts/{draft_id}/submit", json={"remark": ""})
        assert r.json()["order_no"] == no and r.json()["created"] is False

    async with db() as s:
        trade = (await s.execute(select(TradePurchaseOrder).where(TradePurchaseOrder.order_no == no))).scalar_one()
        assert trade.total_amount == Decimal("140800.00") and trade.status == "submitted"
        actions = [a.action for a in (await s.execute(select(AuditLog).where(AuditLog.order_no == no))).scalars()]
        assert actions == ["submit", "return", "resubmit"]


async def test_reject_releases_quota_and_is_final(db):
    draft_id = await _new_draft(db, "jbr01", _data("2026-CG-031", "purchase", "CEM-PO-425", "500", "440"))
    no, status, _ = await _submit(db, "jbr01", draft_id, remark="追加采购")
    assert status == "pending_special"
    async with api_client(db, "spr01") as c:
        oid = await _order_id(c, no)
        assert (await c.post(f"/api/orders/{oid}/reject", json={"comment": " "})).status_code == 422
        r = await c.post(f"/api/orders/{oid}/reject", json={"comment": "超出合同额度，不予特批"})
        assert r.json()["status"] == "rejected"
        assert (await c.post(f"/api/orders/{oid}/approve", json={})).status_code == 409
    async with api_client(db, "jbr01") as c:
        assert (await c.post(f"/api/orders/{oid}/edit")).status_code == 409
        detail = (await c.get(f"/api/orders/{oid}")).json()
        # 驳回后释放占用：剩余额度恢复 150000
        assert detail["quota"]["remaining_amount"] == "150000.00"
        assert detail["quota"]["after_remaining_amount"] == "150000.00"


async def test_approve_pending_special(db):
    draft_id = await _new_draft(db, "jbr01", _data("2026-CG-031", "purchase", "CEM-PO-425", "500", "440"))
    no, _, _ = await _submit(db, "jbr01", draft_id, remark="追加采购")
    async with api_client(db, "spr01") as c:
        oid = await _order_id(c, no)
        r = await c.post(f"/api/orders/{oid}/approve", json={"comment": "同意特批"})
        assert r.json()["status"] == "approved" and r.json()["approval_comment"] == "同意特批"
        assert [a["action"] for a in r.json()["audits"]] == ["submit", "approve"]
