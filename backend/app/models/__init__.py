"""数据库表模型。金额用 Numeric(14,2)，数量用 Numeric(14,3)。"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Money = Numeric(14, 2)
Qty = Numeric(14, 3)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# 角色
ROLE_OPERATOR = "operator"
ROLE_APPROVER = "approver"
ROLE_ADMIN = "admin"

# 订单类型
SALES = "sales"
PURCHASE = "purchase"

# 草稿状态
DRAFT = "draft"
PENDING_CONFIRM = "pending_confirm"
DRAFT_SUBMITTED = "submitted"

# 订单状态
SUBMITTED = "submitted"
PENDING_SPECIAL = "pending_special"
APPROVED = "approved"
RETURNED = "returned"
REJECTED = "rejected"


class Dept(Base):
    __tablename__ = "dept"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(64))


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16))
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"))
    dept: Mapped[Dept] = relationship(lazy="joined")


class Party(Base):
    """签约单位：客户（销售合同对方）或供应商（采购合同对方）。"""

    __tablename__ = "party"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # customer / supplier


class Project(Base):
    __tablename__ = "project"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    contact: Mapped[str] = mapped_column(String(32))
    phone: Mapped[str] = mapped_column(String(32), default="")


class Material(Base):
    __tablename__ = "material"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    spec: Mapped[str] = mapped_column(String(64), default="")
    unit: Mapped[str] = mapped_column(String(8))
    brand: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    fair_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)


class MaterialAlias(Base):
    __tablename__ = "material_alias"
    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(64), unique=True)
    material_code: Mapped[str] = mapped_column(ForeignKey("material.code"))


class Contract(TimestampMixin, Base):
    __tablename__ = "contract"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_no: Mapped[str] = mapped_column(String(32), unique=True)
    contract_type: Mapped[str] = mapped_column(String(16))
    party_id: Mapped[int] = mapped_column(ForeignKey("party.id"))
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"))
    total_amount: Mapped[Decimal] = mapped_column(Money)
    total_qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(8))
    sign_date: Mapped[date] = mapped_column(Date)
    expire_date: Mapped[date] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=0)

    party: Mapped[Party] = relationship(lazy="joined")
    project: Mapped[Project] = relationship(lazy="joined")
    items: Mapped[list["ContractItem"]] = relationship(lazy="selectin", order_by="ContractItem.id")


class ContractItem(Base):
    __tablename__ = "contract_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contract.id"))
    material_code: Mapped[str] = mapped_column(ForeignKey("material.code"))
    unit_price: Mapped[Decimal] = mapped_column(Money)
    quantity: Mapped[Decimal] = mapped_column(Qty)
    material: Mapped[Material] = relationship(lazy="joined")


class Draft(TimestampMixin, Base):
    __tablename__ = "draft"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"))
    order_type: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default=DRAFT)
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("order.id"), nullable=True)


class Order(TimestampMixin, Base):
    __tablename__ = "order"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True)
    order_type: Mapped[str] = mapped_column(String(16))
    draft_id: Mapped[str] = mapped_column(String(36), unique=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contract.id"), index=True)
    contract_no: Mapped[str] = mapped_column(String(32))
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"), index=True)
    party_name: Mapped[str] = mapped_column(String(128))
    project_name: Mapped[str] = mapped_column(String(128))
    address: Mapped[str] = mapped_column(String(255))
    contact: Mapped[str] = mapped_column(String(64))
    operator_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    operator_name: Mapped[str] = mapped_column(String(32))
    dept_name: Mapped[str] = mapped_column(String(64))
    biz_name: Mapped[str] = mapped_column(String(32))
    purchase_mode: Mapped[str] = mapped_column(String(16))
    biz_tag: Mapped[str] = mapped_column(String(16))
    delivery_date: Mapped[date] = mapped_column(Date)
    total_amount: Mapped[Decimal] = mapped_column(Money)
    total_qty: Mapped[Decimal] = mapped_column(Qty)
    over_quota: Mapped[bool] = mapped_column(Boolean, default=False)
    remark: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), index=True)
    approval_comment: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="chat")  # chat / ocr / excel
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list["OrderItem"]] = relationship(
        lazy="selectin", order_by="OrderItem.seq", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("order.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    material_code: Mapped[str] = mapped_column(ForeignKey("material.code"))
    material_name: Mapped[str] = mapped_column(String(64))
    spec: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(8))
    unit_price: Mapped[Decimal] = mapped_column(Money)
    amount: Mapped[Decimal] = mapped_column(Money)


class OrderNoSeq(Base):
    __tablename__ = "order_no_seq"
    prefix: Mapped[str] = mapped_column(String(8), primary_key=True)
    unit_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    biz_date: Mapped[str] = mapped_column(String(8), primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)


class _TradeOrderMixin:
    """模拟底层商贸系统的订单表，保存同步过去的订单快照。"""

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True)
    contract_no: Mapped[str] = mapped_column(String(32))
    party_name: Mapped[str] = mapped_column(String(128))
    total_amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TradeSalesOrder(_TradeOrderMixin, Base):
    __tablename__ = "trade_sales_order"


class TradePurchaseOrder(_TradeOrderMixin, Base):
    __tablename__ = "trade_purchase_order"


class ImportBatch(Base):
    __tablename__ = "import_batch"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"), index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    success_rows: Mapped[int] = mapped_column(Integer, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="parsed")  # parsed / submitted
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    rows: Mapped[list["ImportRow"]] = relationship(lazy="selectin", order_by="ImportRow.row_no")


class ImportRow(Base):
    __tablename__ = "import_row"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id"), index=True)
    row_no: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16))  # ok / error / submitted / failed
    order_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str] = mapped_column(String(255), default="")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_created", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32), index=True)
    input_text: Mapped[str] = mapped_column(Text, default="")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    order_no: Mapped[str] = mapped_column(String(40), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=3), server_default=func.now(3))


class SystemParam(Base):
    __tablename__ = "system_param"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(String(255), default="")

