"""草稿与订单的数据结构。"""
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

OrderType = Literal["sales", "purchase"]


class DraftItem(BaseModel):
    raw_name: str = ""  # 用户或单据中的原始物资描述
    material_code: str | None = None
    material_name: str = ""
    spec: str = ""
    unit: str = ""
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class DraftData(BaseModel):
    order_type: OrderType = "sales"
    contract_no: str | None = None
    party_name: str = ""
    project_name: str = ""
    address: str = ""
    contact: str = ""
    delivery_date: date | None = None
    remark: str = ""
    biz_name: str = ""
    purchase_mode: str = ""
    biz_tag: str = ""
    operator_name: str = ""
    dept_name: str = ""
    creator_name: str = ""
    created_at: str = ""
    items: list[DraftItem] = Field(default_factory=list)


class Issue(BaseModel):
    field: str
    level: Literal["error", "over", "warning", "info"]
    message: str


class QuotaSummary(BaseModel):
    contract_no: str
    unit: str
    total_amount: Decimal
    used_amount: Decimal
    remaining_amount: Decimal
    total_qty: Decimal
    used_qty: Decimal
    remaining_qty: Decimal
    current_amount: Decimal
    current_qty: Decimal
    after_remaining_amount: Decimal
    over_quota: bool
    low_quota: bool


class DraftView(BaseModel):
    id: str | None = None
    session_id: str | None = None
    status: str
    data: DraftData
    issues: list[Issue]
    quota: QuotaSummary | None = None
    order_no: str | None = None
    order_status: str | None = None
    approval_comment: str = ""


class SubmitRequest(BaseModel):
    remark: str = ""
