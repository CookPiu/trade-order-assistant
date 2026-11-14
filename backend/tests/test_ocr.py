"""单据图片识别（FR-015、US2）：视觉模型输出用固定 JSON 代替，验证校验、映射、超额与审计。"""
import io
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select

from app import llm
from app.core.db import get_session
from app.main import app
from app.models import AuditLog

RECEIPT = {
    "doc_type": "发货签收单",
    "order_type": "purchase",
    "contract_no": "2026-CG-031",
    "supplier": "华东建材供应有限公司",
    "consignee": "科技城项目部",
    "doc_date": "2026-11-14",
    "remark": "科技城项目追加采购",
    "items": [{"raw_name": "42.5水泥", "spec": "P.O42.5 散装", "quantity": 500, "unit": "吨", "amount": "220,000.00"}],
}


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


@asynccontextmanager
async def _client(db):
    async def override():
        async with db() as s:
            yield s

    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={"username": "jbr01", "password": "Demo@2026"})
            client.headers["Authorization"] = f"Bearer {r.json()['token']}"
            yield client
    finally:
        app.dependency_overrides.clear()


def _fake_vision(monkeypatch, out):
    async def fake(_s, _prompt, _image, _mime):
        return out

    monkeypatch.setattr(llm, "vision_json", fake)


async def test_receipt_maps_material_and_flags_over_quota(db, monkeypatch):
    _fake_vision(monkeypatch, RECEIPT)
    async with _client(db) as c:
        r = await c.post("/api/ocr", files={"file": ("receipt.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    item = body["card"]["items"][0]
    assert (item["raw_name"], item["quantity"], item["amount"]) == ("42.5水泥", "500", "220000.00")
    assert item["material_code"] == "CEM-PO-425"
    assert body["data"]["order_type"] == "purchase"
    assert body["data"]["items"][0]["unit_price"] == "440.00"
    assert body["quota"]["over_quota"] is True
    assert any(i["level"] == "over" for i in body["issues"])
    assert body["data"]["remark"] == ""  # 单据备注只展示在卡片上，超额备注由经办人填写
    async with db() as s:
        log = (await s.execute(select(AuditLog).where(AuditLog.action == "image_recognize"))).scalar_one()
    assert len(log.input_hash) == 64


async def test_no_items_asks_reupload(db, monkeypatch):
    _fake_vision(monkeypatch, {"doc_type": "其他", "items": []})
    async with _client(db) as c:
        r = await c.post("/api/ocr", files={"file": ("blank.png", _png(), "image/png")})
    assert r.status_code == 422
    assert "重新上传" in r.json()["detail"]


async def test_rejects_non_image(db, monkeypatch):
    _fake_vision(monkeypatch, RECEIPT)
    async with _client(db) as c:
        r = await c.post("/api/ocr", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    assert "JPG 或 PNG" in r.json()["detail"]
