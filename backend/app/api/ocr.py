"""单据图片识别（FR-015、FR-003、US2）。

识别结果走与对话相同的物料标准化和合同装配链路，返回识别卡片和装配后的草稿内容；
经办人在识别卡片上点击“应用为草稿”后，前端再调用草稿保存接口落库。
"""
import io
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import llm
from app.core import clock
from app.core.db import get_session
from app.core.errors import BizError
from app.core.security import require_roles
from app.graph.nodes import compose_reply, llm_picker, normalize_items
from app.models import ROLE_OPERATOR, User
from app.schemas import DraftData, DraftItem, Issue, QuotaSummary
from app.services import audit, draft_validator

router = APIRouter(prefix="/api/ocr", tags=["ocr"])
operator = require_roles(ROLE_OPERATOR)
log = logging.getLogger(__name__)

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "recognize.md"
MAX_BYTES = 10 * 1024 * 1024
FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png"}


class CardItem(BaseModel):
    raw_name: str
    spec: str
    quantity: Decimal | None
    unit: str
    amount: Decimal | None
    material_code: str | None
    material_name: str


class RecognizeCard(BaseModel):
    doc_type: str
    contract_no: str | None
    supplier: str
    consignee: str
    doc_date: str | None
    remark: str
    items: list[CardItem]


class RecognizeResponse(BaseModel):
    image_hash: str
    card: RecognizeCard
    reply: str
    data: DraftData
    issues: list[Issue]
    quota: QuotaSummary | None = None


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", "").replace("，", ""))
    except InvalidOperation:
        return None


def _str(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _check_image(raw: bytes) -> str:
    if not raw:
        raise BizError(400, "图片为空，请重新上传")
    if len(raw) > MAX_BYTES:
        raise BizError(400, "图片超过 10 MB，请压缩后重新上传")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, OSError) as e:
        raise BizError(400, "无法读取图片，请上传 JPG 或 PNG 格式") from e
    if fmt not in FORMATS:
        raise BizError(400, "只支持 JPG 或 PNG 格式的图片")
    return FORMATS[fmt]


async def build_draft(
    session: AsyncSession, user: User, extracted: dict[str, Any], picker=None
) -> tuple[DraftData, list[str]]:
    """把视觉模型输出转换为草稿：合同存在且属于本部门时按合同类型定订单类型。"""
    data = DraftData()
    contract_no = _str(extracted.get("contract_no")) or None
    contract = await draft_validator.find_contract(session, contract_no) if contract_no else None
    if contract is not None and contract.dept_id != user.dept_id:
        contract = None
    if contract is not None:
        data.order_type = contract.contract_type
    elif extracted.get("order_type") in ("sales", "purchase"):
        data.order_type = extracted["order_type"]
    else:
        data.order_type = "purchase"
    data.contract_no = contract_no
    for raw in extracted.get("items") or []:
        if not isinstance(raw, dict) or not _str(raw.get("raw_name")):
            continue
        data.items.append(
            DraftItem(
                raw_name=_str(raw.get("raw_name")),
                spec=_str(raw.get("spec")),
                unit=_str(raw.get("unit")),
                quantity=_dec(raw.get("quantity")),
                unit_price=_dec(raw.get("unit_price")),
                amount=_dec(raw.get("amount")),
            )
        )
    notes = await normalize_items(session, data, contract, picker)
    return data, notes


@router.post("", response_model=RecognizeResponse)
async def recognize(
    file: UploadFile = File(...),
    user: User = Depends(operator),
    session: AsyncSession = Depends(get_session),
):
    raw = await file.read(MAX_BYTES + 1)
    mime = _check_image(raw)
    image_hash = audit.sha256_hex(raw)
    try:
        extracted = await llm.vision_json(session, PROMPT.read_text(encoding="utf-8"), raw, mime)
    except llm.LLMError as e:
        raise BizError(502, f"{e}，请稍后重试") from e

    data, notes = await build_draft(session, user, extracted, llm_picker(session))
    audit.record(
        session,
        user,
        audit.IMAGE_RECOGNIZE,
        input_hash=image_hash,
        detail={"filename": file.filename or "", "items": len(data.items), "contract_no": data.contract_no},
    )
    if not data.items:
        await session.commit()
        raise BizError(422, "图片中没有识别出物资信息，请重新上传清晰的单据照片")

    # 识别出的原文与规格保存在卡片里；装配会把映射成功的物料改为字典规格
    card_items = [(i.raw_name, i.spec, i.quantity, i.unit, i.amount) for i in data.items]
    candidates = [i.candidates for i in data.items]
    assembled = await draft_validator.assemble(session, user, data, today=clock.today())
    for item, cands in zip(assembled.data.items, candidates):
        if cands and not item.candidates:
            item.candidates = cands
    await session.commit()

    card = RecognizeCard(
        doc_type=_str(extracted.get("doc_type")) or "其他",
        contract_no=data.contract_no,
        supplier=_str(extracted.get("supplier")),
        consignee=_str(extracted.get("consignee")),
        doc_date=_str(extracted.get("doc_date")) or None,
        remark=_str(extracted.get("remark")),
        items=[
            CardItem(
                raw_name=name,
                spec=spec,
                quantity=qty,
                unit=unit,
                amount=amount,
                material_code=item.material_code,
                material_name=item.material_name,
            )
            for (name, spec, qty, unit, amount), item in zip(card_items, assembled.data.items)
        ],
    )
    return RecognizeResponse(
        image_hash=image_hash,
        card=card,
        reply=compose_reply(assembled, notes),
        data=assembled.data,
        issues=assembled.issues,
        quota=assembled.quota_summary(),
    )
