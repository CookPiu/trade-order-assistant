"""主数据与系统配置（FR-050、FR-051、FR-052、US6）。"""
from datetime import timedelta

from app.core import clock
from app.schemas import DraftData
from app.services.material_normalizer import normalize
from tests._api import api_client
from tests.conftest import get_user
from tests.test_chat_graph import _run

ALIAS = "小十六螺"


async def test_new_alias_is_used_by_chat(db, monkeypatch):
    async with db() as s:
        assert (await normalize(s, ALIAS)).method != "exact"

    async with api_client(db, "admin") as c:
        r = await c.post("/api/admin/aliases", json={"alias": ALIAS, "material_code": "STL-RB-400E-16"})
        assert r.status_code == 200, r.text
        # 去空格后相同的别名、字典外的编码都被拒绝
        assert (await c.post("/api/admin/aliases", json={"alias": "小 十六 螺", "material_code": "STL-RB-400E-20"})).status_code == 409
        assert (await c.post("/api/admin/aliases", json={"alias": "新别名", "material_code": "NOT-EXIST"})).status_code == 422
        logs = (await c.get("/api/audit", params={"action": "master_update"})).json()
        assert logs["items"][0]["detail"]["key"] == ALIAS

    extracted = {
        "intent": "new_sales", "order_type": "sales", "contract_no": "2026-WZ-089", "delivery_text": "后天",
        "items": [{"raw_name": ALIAS, "spec": "", "quantity": 10, "unit": "吨", "unit_price": None, "amount": None}],
    }
    async with db() as s:
        user = await get_user(s, "jbr01")
        state = await _run(s, user, f"走 2026-WZ-089 合同下 10 吨{ALIAS}，后天送", DraftData(), extracted, monkeypatch)
    d = state["assembled"].data
    assert d.items[0].material_code == "STL-RB-400E-16"
    assert d.delivery_date == clock.today() + timedelta(days=2)


async def test_contract_and_material_create_update(db):
    body = {
        "contract_no": "2026-WZ-901", "contract_type": "sales", "dept_id": 1,
        "party_name": "测试客户有限公司", "project_name": "测试项目", "address": "测试路 1 号", "contact": "张三",
        "phone": "", "total_amount": "100000", "total_qty": "20", "unit": "吨",
        "sign_date": "2026-01-01", "expire_date": "2026-12-31",
        "items": [{"material_code": "STL-RB-400E-20", "unit_price": "3600", "quantity": "20"}],
    }
    async with api_client(db, "admin") as c:
        r = await c.post("/api/admin/contracts", json=body)
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        assert (await c.post("/api/admin/contracts", json=body)).status_code == 409
        bad = {**body, "contract_no": "2026-WZ-902", "items": [{"material_code": "X-1", "unit_price": "1", "quantity": "1"}]}
        assert (await c.post("/api/admin/contracts", json=bad)).status_code == 422

        upd = {**body, "total_amount": "150000",
               "items": [{"material_code": "STL-RB-400E-16", "unit_price": "3700", "quantity": "20"}]}
        r = await c.put(f"/api/admin/contracts/{cid}", json=upd)
        assert r.status_code == 200, r.text
        v = r.json()
        assert float(v["total_amount"]) == 150000 and v["version"] == 1
        assert [i["material_code"] for i in v["items"]] == ["STL-RB-400E-16"]

        m = {"code": "TST-001", "name": "测试物料", "spec": "1#", "unit": "件", "brand": "", "category": "", "fair_price": "10"}
        assert (await c.post("/api/admin/materials", json=m)).status_code == 200
        r = await c.put("/api/admin/materials/TST-001", json={**m, "fair_price": "12.5"})
        assert float(r.json()["fair_price"]) == 12.5
        assert (await c.put("/api/admin/materials/TST-001", json={**m, "code": "TST-002"})).status_code == 422

    # 新合同按部门对经办人可见
    async with api_client(db, "jbr01") as c:
        assert (await c.get("/api/master/contracts/2026-WZ-901")).status_code == 200


async def test_params_validate_and_take_effect(db):
    async with api_client(db, "admin") as c:
        keys = [p["key"] for p in (await c.get("/api/params")).json()]
        assert keys == ["fixed_attrs", "fair_price_deviation", "quota_warn_ratio", "llm", "vision"]
        assert (await c.put("/api/params/fair_price_deviation", json={"value": 1.5})).status_code == 422
        r = await c.put("/api/params/quota_warn_ratio", json={"value": 0.2})
        assert r.status_code == 200 and r.json()["value"] == 0.2
        r = await c.put("/api/params/llm", json={"value": {"model": "", "temperature": 0.3, "timeout": 20, "thinking": False}})
        assert r.json()["value"]["temperature"] == 0.3
        assert (await c.put("/api/params/llm", json={"value": {"temperature": 3, "timeout": 20}})).status_code == 422
        assert (await c.put("/api/params/fixed_attrs", json={"value": {"biz_name": "", "purchase_mode": "直发", "biz_tag": "x"}})).status_code == 422
        logs = (await c.get("/api/audit", params={"action": "param_update"})).json()
        assert logs["total"] == 2
        assert {i["detail"]["key"] for i in logs["items"]} == {"quota_warn_ratio", "llm"}


async def test_audit_filters_and_admin_only(db):
    async with api_client(db, "jbr01") as c:
        assert (await c.get("/api/audit")).status_code == 403
        assert (await c.get("/api/params")).status_code == 403
        assert (await c.get("/api/admin/materials")).status_code == 403
    async with api_client(db, "spr01") as c:
        assert (await c.post("/api/admin/aliases", json={"alias": "a", "material_code": "STL-RB-400E-16"})).status_code == 403
    async with api_client(db, "admin") as c:
        today = clock.today().isoformat()
        r = (await c.get("/api/audit", params={"username": "jbr01", "action": "login"})).json()
        assert r["total"] >= 1 and {i["username"] for i in r["items"]} == {"jbr01"}
        assert {i["action"] for i in r["items"]} == {"login"}
        r = (await c.get("/api/audit", params={"username": "spr01", "date_from": today, "date_to": today})).json()
        assert r["total"] >= 1
        r = (await c.get("/api/audit", params={"date_to": "2000-01-01"})).json()
        assert r["total"] == 0
        opts = (await c.get("/api/audit/options")).json()
        assert "master_update" in opts["actions"] and any(u["username"] == "jbr01" for u in opts["users"])
