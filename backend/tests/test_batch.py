"""Excel 批量提单（US3、SC-005）：三类异常行、批内累计额度、行内修正、逐行提交。"""
import io
from contextlib import asynccontextmanager
from datetime import timedelta

from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy import select

from app.api.batch import get_maker
from app.core import clock
from app.core.db import get_session
from app.main import app
from app.models import PENDING_SPECIAL, SUBMITTED, Order
from scripts.make_samples import make_batch_excel

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@asynccontextmanager
async def _client(db):
    async def override():
        async with db() as s:
            yield s

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_maker] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={"username": "jbr01", "password": "Demo@2026"})
            client.headers["Authorization"] = f"Bearer {r.json()['token']}"
            yield client
    finally:
        app.dependency_overrides.clear()


def _sample(tmp_path) -> bytes:
    p = tmp_path / "batch.xlsx"
    make_batch_excel(p, clock.today())
    return p.read_bytes()


def _by_row(view):
    return {r["row_no"]: r for r in view["rows"]}


async def test_sample_rows_flagged_then_fixed_and_submitted(db, tmp_path):
    async with _client(db) as c:
        r = await c.post("/api/batch", files={"file": ("批量订单示例.xlsx", _sample(tmp_path), XLSX)})
        assert r.status_code == 200, r.text
        view = r.json()
        rows = _by_row(view)
        assert view["total_rows"] == 10
        status = {n: rows[n]["status"] for n in rows}
        # 合同号错误、单价缺失、超额未填备注、交期晚于到期日
        assert status[5] == "error" and "不存在" in rows[5]["message"]
        assert status[6] == "error" and "缺少含税单价" in rows[6]["message"]
        assert status[8] == "error" and "超出合同剩余" in rows[8]["message"]
        assert status[11] == "error" and "晚于合同到期日" in rows[11]["message"]
        assert all(status[n] == "ok" for n in (2, 3, 4, 7, 9, 10)), status
        # 批内累计：第 7 行占用 88000 后，第 8 行按剩余 62000 判断
        assert rows[8]["result"]["remaining_amount"] == "62000.00"
        assert rows[2]["result"]["material_code"] == "STL-RB-400E-20"

        def body(row, **changes):
            return {**row["input"], **changes}

        r = await c.put(f"/api/batch/{view['id']}/rows/{rows[5]['id']}", json=body(rows[5], contract_no="2026-WZ-089"))
        r = await c.put(f"/api/batch/{view['id']}/rows/{rows[6]['id']}", json=body(rows[6], unit_price="3650"))
        r = await c.put(f"/api/batch/{view['id']}/rows/{rows[8]['id']}", json=body(rows[8], remark="项目追加采购"))
        rows = _by_row(r.json())
        assert rows[5]["status"] == "ok" and rows[6]["status"] == "ok"
        assert rows[8]["status"] == "over"
        assert rows[11]["status"] == "error"

        r = await c.post(f"/api/batch/{view['id']}/submit")
        assert r.status_code == 200, r.text
        done = r.json()
        rows = _by_row(done)
    assert done["success_rows"] == 9 and done["failed_rows"] == 1
    assert rows[11]["status"] == "error" and rows[11]["order_no"] is None
    nos = {n: rows[n]["order_no"] for n in rows if n != 11}
    assert all(nos.values()) and len(set(nos.values())) == 9
    assert nos[7].startswith("CGDD-") and nos[2].startswith("XSDD-")
    async with db() as s:
        orders = {o.order_no: o for o in (await s.execute(select(Order).where(Order.source == "excel"))).scalars()}
    assert orders[nos[8]].status == PENDING_SPECIAL and orders[nos[8]].over_quota
    assert orders[nos[7]].status == SUBMITTED


async def test_missing_columns_rejected(db):
    wb = Workbook()
    wb.active.append(["单据类型", "合同编号", "数量"])
    wb.active.append(["销售", "2026-WZ-089", 1])
    buf = io.BytesIO()
    wb.save(buf)
    async with _client(db) as c:
        r = await c.post("/api/batch", files={"file": ("bad.xlsx", buf.getvalue(), XLSX)})
    assert r.status_code == 400
    assert "物料名称" in r.json()["detail"] and "交期" in r.json()["detail"]


async def test_empty_file_rejected(db):
    wb = Workbook()
    wb.active.append(["单据类型", "合同编号", "物料名称", "规格", "数量", "单价", "交期", "备注"])
    buf = io.BytesIO()
    wb.save(buf)
    async with _client(db) as c:
        r = await c.post("/api/batch", files={"file": ("empty.xlsx", buf.getvalue(), XLSX)})
    assert r.status_code == 400
    assert "没有可导入的订单" in r.json()["detail"]


async def test_bad_date_and_template(db):
    wb = Workbook()
    wb.active.append(["单据类型", "合同编号", "物料名称", "规格", "数量", "单价", "交期", "备注"])
    wb.active.append(["销售", "2026-WZ-089", "螺纹钢20", "", "abc", 3650, "下个月", ""])
    wb.active.append(["销售", "2026-WZ-089", "螺纹钢20", "", 10, 3650, (clock.today() + timedelta(days=3)).isoformat(), ""])
    buf = io.BytesIO()
    wb.save(buf)
    async with _client(db) as c:
        r = await c.post("/api/batch", files={"file": ("x.xlsx", buf.getvalue(), XLSX)})
        rows = _by_row(r.json())
        t = await c.get("/api/batch/template")
    assert "数量不是有效数字" in rows[2]["message"] and "交期不是有效日期" in rows[2]["message"]
    assert rows[3]["status"] == "ok"
    assert t.status_code == 200 and t.content[:2] == b"PK"
