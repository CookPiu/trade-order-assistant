"""提单图节点：extract → merge → normalize_material → link_contract（装配与校验）→ respond。

节点通过 config["configurable"] 取得数据库会话、当前用户和模型选择函数。
"""
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from app import llm
from app.models import Contract, User
from app.schemas import DraftData, DraftItem
from app.services import draft_validator, material_normalizer
from app.services.date_phrase import parse_date_phrase

PROMPTS = Path(__file__).resolve().parents[3] / "prompts"
TYPE_LABEL = {"sales": "销售订单", "purchase": "采购订单"}

HELP_TEXT = (
    "可以直接用一句话描述订单，例如：“给中建八局科技城项目下 200 吨 HRB400E 螺纹钢，走 2026-WZ-089 合同，后天送到一号工地”。"
    "我会识别合同号、物资、数量和交期，关联合同补全签约单位和收货信息，并计算合同剩余额度。"
    "缺少的信息会在右侧标红并在这里追问，你可以继续对话补充，也可以直接在右侧修改。"
    "单据照片和批量 Excel 请切换到对应面板上传。"
)


class ChatState(TypedDict, total=False):
    message: str
    today: date
    draft: dict[str, Any]
    intent: str
    extracted: dict[str, Any]
    notes: list[str]
    type_from_contract: bool
    reply: str
    assembled: Any


def _ctx(config: RunnableConfig) -> tuple[AsyncSession, User]:
    c = config["configurable"]
    return c["session"], c["user"]


def _draft_summary(d: DraftData) -> dict[str, Any]:
    return {
        "order_type": d.order_type,
        "contract_no": d.contract_no,
        "project_name": d.project_name or None,
        "delivery_date": d.delivery_date.isoformat() if d.delivery_date else None,
        "address": d.address or None,
        "contact": d.contact or None,
        "remark": d.remark or None,
        "items": [
            {
                "raw_name": i.raw_name or f"{i.material_name} {i.spec}".strip(),
                "spec": i.spec if not i.material_code else "",
                "quantity": float(i.quantity) if i.quantity is not None else None,
                "unit": i.unit or None,
                "unit_price": float(i.unit_price) if i.unit_price is not None else None,
            }
            for i in d.items
        ],
    }


async def extract(state: ChatState, config: RunnableConfig) -> ChatState:
    session, _ = _ctx(config)
    current = DraftData.model_validate(state.get("draft") or {})
    system = (PROMPTS / "extract.md").read_text(encoding="utf-8")
    user_msg = (
        f"今天是 {state['today'].isoformat()}。\n"
        f"当前草稿：{json.dumps(_draft_summary(current), ensure_ascii=False)}\n"
        f"用户本轮消息：{state['message']}"
    )
    data = await llm.chat_json(session, system, user_msg)
    return {"extracted": data, "intent": str(data.get("intent") or "modify")}


def route_after_extract(state: ChatState) -> str:
    return "help" if state.get("intent") in ("help", "chat") else "merge"


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def merge(state: ChatState, config: RunnableConfig) -> ChatState:
    """把抽取结果合并进当前草稿（FR-012）。已映射的物料在原始叫法未变时保留编码。"""
    current = DraftData.model_validate(state.get("draft") or {})
    ex = state["extracted"]
    notes: list[str] = []
    d = current.model_copy(deep=True)
    type_stated = True
    if ex.get("order_type") in ("sales", "purchase"):
        d.order_type = ex["order_type"]
    elif state.get("intent") == "new_purchase":
        d.order_type = "purchase"
    else:
        type_stated = False
    for f in ("contract_no", "project_name", "address", "contact", "remark"):
        if ex.get(f):
            setattr(d, f, str(ex[f]).strip())
    # 本轮未说明单据类型且关联了新合同时，在 normalize_material 中按合同类型确定（与图片识别一致）
    type_from_contract = not type_stated and bool(d.contract_no) and d.contract_no != current.contract_no
    if ex.get("delivery_text"):
        parsed = parse_date_phrase(ex["delivery_text"], state["today"])
        if parsed is None:
            notes.append(f"交期“{ex['delivery_text']}”无法识别为具体日期，请写明日期")
        d.delivery_date = parsed
    if isinstance(ex.get("items"), list):
        old = {(i.raw_name, i.spec): i for i in current.items}
        items = []
        for raw in ex["items"]:
            if not isinstance(raw, dict):
                continue
            name, spec = str(raw.get("raw_name") or "").strip(), str(raw.get("spec") or "").strip()
            prev = old.get((name, spec)) or next((i for i in current.items if i.raw_name == name), None)
            item = DraftItem(
                raw_name=name,
                quantity=_dec(raw.get("quantity")),
                unit_price=_dec(raw.get("unit_price")),
                amount=_dec(raw.get("amount")),
                spec=spec,
                unit=str(raw.get("unit") or ""),
            )
            if prev is not None and prev.material_code:
                item.material_code = prev.material_code
                if item.unit_price is None and item.amount is None:
                    item.unit_price = prev.unit_price
            items.append(item)
        d.items = items
    return {"draft": d.model_dump(mode="json"), "notes": notes, "type_from_contract": type_from_contract}


def llm_picker(session: AsyncSession):
    async def pick(raw: str, cands: list[dict]) -> str | None:
        system = (PROMPTS / "pick_material.md").read_text(encoding="utf-8")
        listing = "\n".join(f"{c['code']}：{c['name']} {c['spec']}" for c in cands)
        try:
            out = await llm.chat_json(session, system, f"用户叫法：{raw}\n候选：\n{listing}")
        except llm.LLMError:
            return None
        code = out.get("code")
        return code if isinstance(code, str) else None

    return pick


async def normalize_items(
    session: AsyncSession, data: DraftData, contract: Contract | None, picker=None
) -> list[str]:
    """为未映射的物资匹配标准编码，返回需要告知用户的说明。"""
    notes = []
    items = contract.items if contract is not None else None
    for item in data.items:
        if item.material_code:
            continue
        m = await material_normalizer.normalize(session, item.raw_name, item.spec, items, picker)
        item.material_code = m.code
        item.candidates = m.candidates if (m.code is None or m.method == "contract_primary") else []
        if m.note:
            notes.append(f"“{item.raw_name}”{m.note}")
    return notes


async def normalize_material(state: ChatState, config: RunnableConfig) -> ChatState:
    session, user = _ctx(config)
    d = DraftData.model_validate(state["draft"])
    contract = None
    if d.contract_no:
        contract = await draft_validator.find_contract(session, d.contract_no)
        if contract is not None and contract.dept_id != user.dept_id:
            contract = None
    notes = []
    if contract is not None and state.get("type_from_contract") and d.order_type != contract.contract_type:
        d.order_type = contract.contract_type
        label = draft_validator.TYPE_LABEL[contract.contract_type]
        notes.append(f"合同 {contract.contract_no} 是{label}合同，已按合同设为{label}订单")
    notes += await normalize_items(session, d, contract, config["configurable"].get("picker"))
    # 用户只说了工地简称时，用项目登记的完整收货地址
    if contract is not None and d.address and d.address in contract.project.address:
        d.address = contract.project.address
    return {"draft": d.model_dump(mode="json"), "notes": state.get("notes", []) + notes}


async def link_contract(state: ChatState, config: RunnableConfig) -> ChatState:
    session, user = _ctx(config)
    d = DraftData.model_validate(state["draft"])
    candidates = [i.candidates for i in d.items]
    assembled = await draft_validator.assemble(
        session, user, d, today=state["today"], exclude_order_id=config["configurable"].get("exclude_order_id")
    )
    # 装配会清空已映射物料的候选，按需保留“默认取合同首项”时的候选供切换
    for item, cands in zip(assembled.data.items, candidates):
        if cands and not item.candidates:
            item.candidates = cands
    return {"assembled": assembled, "draft": assembled.data.model_dump(mode="json")}


def fmt_num(v: Decimal | None) -> str:
    """数量去掉多余的小数位：80.0 → 80，12.500 → 12.5。"""
    if v is None:
        return "?"
    s = format(v, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def compose_reply(assembled: draft_validator.Assembled, notes: list[str]) -> str:
    d = assembled.data
    parts = [f"已识别{TYPE_LABEL[d.order_type]}"]
    if d.contract_no and assembled.contract is not None:
        parts.append(f"合同 {d.contract_no}（{d.party_name}，{d.project_name}）")
    for i in d.items:
        if i.material_code:
            parts.append(f"{i.material_name} {i.spec} {fmt_num(i.quantity)} {i.unit}".strip())
    if d.delivery_date:
        parts.append(f"交期 {d.delivery_date}")
    lines = ["，".join(parts) + "。"]
    lines += notes
    errors = assembled.errors
    if errors:
        lines.append("还需要确认：")
        lines += [f"{n}. {e.message}" for n, e in enumerate(errors, 1)]
        lines.append("可以继续告诉我，也可以直接在右侧修改。")
    over = [i for i in assembled.issues if i.level == "over"]
    if over:
        lines.append(f"超额警告：{over[0].message}。")
    warns = [i.message for i in assembled.issues if i.level == "warning"]
    if warns:
        lines.append("提醒：" + "；".join(warns) + "。")
    if not errors:
        lines.append("草稿已生成，核对无误后可点击“一键提单”。")
    return "\n".join(lines)


def respond(state: ChatState) -> ChatState:
    return {"reply": compose_reply(state["assembled"], state.get("notes", []))}


def respond_help(state: ChatState) -> ChatState:
    return {"reply": HELP_TEXT}
