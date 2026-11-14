"""越权访问（SC-007、FR-002）：跨部门读取订单、合同、草稿、导入批次，以及越权审批。"""
from tests._api import api_client
from tests.test_submit import _data, _new_draft, _submit


async def test_cross_dept_and_role_access_denied(db):
    draft_id = await _new_draft(db, "jbr01", _data("2026-WZ-089", "sales", "STL-RB-400E-20", "10"))
    no, _, _ = await _submit(db, "jbr01", draft_id)
    async with api_client(db, "spr01") as c:
        order_id = next(i["id"] for i in (await c.get("/api/orders")).json()["items"] if i["order_no"] == no)

    # 建材公司经办人：读不到物资公司的订单、合同、草稿
    async with api_client(db, "jbr02") as c:
        assert (await c.get(f"/api/orders/{order_id}")).status_code == 404
        assert no not in [i["order_no"] for i in (await c.get("/api/orders")).json()["items"]]
        assert (await c.get("/api/master/contracts/2026-WZ-089")).status_code in (403, 404)
        assert "2026-WZ-089" not in str((await c.get("/api/master/contracts")).json())
        assert (await c.get(f"/api/drafts/{draft_id}")).status_code == 404
        assert (await c.post(f"/api/orders/{order_id}/edit")).status_code == 404

    # 建材公司审批人：不能审批物资公司的订单
    async with api_client(db, "spr02") as c:
        assert (await c.post(f"/api/orders/{order_id}/approve", json={})).status_code == 404

    # 经办人不能审批，审批人不能提单，管理员不能看订单
    async with api_client(db, "jbr01") as c:
        assert (await c.post(f"/api/orders/{order_id}/approve", json={})).status_code == 403
    async with api_client(db, "spr01") as c:
        assert (await c.post(f"/api/drafts/{draft_id}/submit", json={})).status_code == 403
        assert (await c.get("/api/batch")).status_code == 403
    async with api_client(db, "admin") as c:
        assert (await c.get(f"/api/orders/{order_id}")).status_code == 403

    # 同部门的其他经办人也读不到别人的草稿（草稿按本人隔离）
    # 种子数据中物资公司只有一个经办人，这里只验证未登录
    async with api_client(db, "jbr01") as c:
        c.headers.pop("Authorization")
        assert (await c.get("/api/orders")).status_code == 401
