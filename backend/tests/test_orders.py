"""商贸订单列表与详情（FR-035、FR-002）：筛选、部门隔离、详情含明细额度与审计流水。"""
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import app
from tests.test_submit import _data, _new_draft, _submit


@asynccontextmanager
async def _client(db, username: str):
    async def override():
        async with db() as s:
            yield s

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={"username": username, "password": "Demo@2026"})
            client.headers["Authorization"] = f"Bearer {r.json()['token']}"
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_list_filters_detail_and_isolation(db):
    sales_no = (await _submit(db, "jbr01", await _new_draft(db, "jbr01", _data("2026-WZ-089", "sales", "STL-RB-400E-20", "200"))))[0]
    over_no = (
        await _submit(
            db, "jbr01",
            await _new_draft(db, "jbr01", _data("2026-CG-031", "purchase", "CEM-PO-425", "500", "440")),
            remark="追加采购",
        )
    )[0]

    async with _client(db, "spr01") as c:
        r = await c.get("/api/orders", params={"order_type": "purchase", "status": "submitted,pending_special"})
        page = r.json()
        nos = [i["order_no"] for i in page["items"]]
        assert over_no in nos and sales_no not in nos
        # 种子数据里的历史已审核订单不在待审筛选中
        assert all(i["status"] in ("submitted", "pending_special") for i in page["items"])
        r = await c.get("/api/orders", params={"contract_no": "WZ-089"})
        assert [i["order_no"] for i in r.json()["items"]] == [sales_no]

        over = next(i for i in page["items"] if i["order_no"] == over_no)
        d = (await c.get(f"/api/orders/{over['id']}")).json()
        assert d["over_quota"] is True and d["status"] == "pending_special"
        assert d["items"][0]["material_code"] == "CEM-PO-425"
        assert d["quota"]["remaining_amount"] == "150000.00"
        assert d["quota"]["current_amount"] == "220000.00"
        assert any(a["action"] == "submit" for a in d["audits"])
        order_id = over["id"]

    # 其他部门看不到
    async with _client(db, "jbr02") as c:
        assert (await c.get(f"/api/orders/{order_id}")).status_code == 404
        r = await c.get("/api/orders")
        assert over_no not in [i["order_no"] for i in r.json()["items"]]

    # 管理员无权访问订单列表
    async with _client(db, "admin") as c:
        assert (await c.get("/api/orders")).status_code == 403
