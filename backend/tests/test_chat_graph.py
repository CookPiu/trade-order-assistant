"""对话提单图（FR-011、FR-012、US1）：模型输出用固定 JSON 代替，验证合并、映射、装配与回复。"""
from datetime import date, timedelta

import pytest

from app.core import clock
from app import llm
from app.graph.graph import build_graph
from app.schemas import DraftData
from app.services.date_phrase import parse_date_phrase
from tests.conftest import get_user

TODAY = date(2026, 11, 14)  # 周六


@pytest.mark.parametrize(
    "text,expect",
    [
        ("后天", TODAY + timedelta(days=2)),
        ("明天上午", TODAY + timedelta(days=1)),
        ("大后天", TODAY + timedelta(days=3)),
        ("3天内", TODAY + timedelta(days=3)),
        ("三天后", TODAY + timedelta(days=3)),
        ("11月20日", date(2026, 11, 20)),
        ("2026-12-01", date(2026, 12, 1)),
        ("下周三", date(2026, 11, 18)),
        ("周一", date(2026, 11, 16)),
        ("1月5号", date(2027, 1, 5)),
        ("月底", date(2026, 11, 30)),
        ("尽快", None),
    ],
)
def test_parse_date_phrase(text, expect):
    assert parse_date_phrase(text, TODAY) == expect


async def _run(session, user, message, draft: DraftData, extracted: dict, monkeypatch):
    async def fake_chat_json(_s, _system, _user):
        return extracted

    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    return await build_graph().ainvoke(
        {"message": message, "today": clock.today(), "draft": draft.model_dump(mode="json")},
        config={"configurable": {"session": session, "user": user, "picker": None}},
    )


async def test_scenario_one_then_modify(db, monkeypatch):
    msg = "给中建八局科技城项目下 200 吨 HRB400E 螺纹钢，走 2026-WZ-089 合同，后天送到一号工地"
    extracted = {
        "intent": "new_sales",
        "order_type": "sales",
        "contract_no": "2026-WZ-089",
        "project_name": "科技城项目",
        "delivery_text": "后天",
        "address": "一号工地",
        "items": [{"raw_name": "HRB400E 螺纹钢", "spec": "", "quantity": 200, "unit": "吨", "unit_price": None, "amount": None}],
    }
    async with db() as s:
        user = await get_user(s, "jbr01")
        state = await _run(s, user, msg, DraftData(), extracted, monkeypatch)
    a = state["assembled"]
    d = a.data
    assert a.errors == []
    assert d.items[0].material_code == "STL-RB-400E-20"
    assert d.delivery_date == clock.today() + timedelta(days=2)
    assert d.address == "科技城大道 88 号一号工地"
    assert d.party_name == "中建八局第三建设有限公司"
    assert "草稿已生成" in state["reply"]
    assert "Φ20 200 吨" in state["reply"]
    assert "默认取合同首项物料" in state["reply"]
    assert d.items[0].candidates  # 保留候选供切换

    # 第二轮只改数量：沿用已映射物料，合并到同一草稿
    extracted2 = {**extracted, "intent": "modify", "delivery_text": d.delivery_date.isoformat(),
                  "items": [{"raw_name": "HRB400E 螺纹钢", "spec": "", "quantity": 300, "unit": "吨"}]}
    async with db() as s:
        user = await get_user(s, "jbr01")
        state2 = await _run(s, user, "数量改成 300 吨", d, extracted2, monkeypatch)
    d2 = state2["assembled"].data
    assert d2.items[0].material_code == "STL-RB-400E-20"
    assert str(d2.items[0].quantity) == "300"
    assert d2.items[0].amount == 300 * d.items[0].unit_price


async def test_missing_contract_asks_back(db, monkeypatch):
    extracted = {"intent": "new_sales", "order_type": "sales", "contract_no": None, "delivery_text": "明天",
                 "items": [{"raw_name": "螺纹钢20", "spec": "", "quantity": 10, "unit": "吨"}]}
    async with db() as s:
        user = await get_user(s, "jbr01")
        state = await _run(s, user, "要10吨螺纹钢20 明天到", DraftData(), extracted, monkeypatch)
    assert state["assembled"].status == "pending_confirm"
    assert "缺少合同编号" in state["reply"]
    assert "还需要确认" in state["reply"]


async def test_help_intent_skips_draft(db, monkeypatch):
    async with db() as s:
        user = await get_user(s, "jbr01")
        state = await _run(s, user, "怎么用", DraftData(), {"intent": "help"}, monkeypatch)
    assert state.get("assembled") is None
    assert "一句话描述订单" in state["reply"]
