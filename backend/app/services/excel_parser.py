"""Excel 导入模板与逐行解析（FR-017、D-011）：一行对应一笔只含一种物资的订单。"""
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError
from app.graph.nodes import normalize_items
from app.models import ImportBatch, User
from app.schemas import DraftData, DraftItem, Issue
from app.services import draft_validator, quota

HEADERS = ["单据类型", "合同编号", "物料名称", "规格", "数量", "单价", "交期", "备注"]
REQUIRED = ["单据类型", "合同编号", "物料名称", "数量", "单价", "交期"]
FIELDS = {
    "单据类型": "order_type",
    "合同编号": "contract_no",
    "物料名称": "raw_name",
    "规格": "spec",
    "数量": "quantity",
    "单价": "unit_price",
    "交期": "delivery_date",
    "备注": "remark",
}
MAX_ROWS = 500


def template_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "订单"
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E8C")
    ws.append(["销售", "2026-WZ-089", "螺纹钢20", "HRB400E", 50, 3650, "2026-12-01", ""])
    for col, width in zip("ABCDEFGH", (10, 16, 14, 12, 10, 10, 14, 24)):
        ws.column_dimensions[col].width = width
    note = wb.create_sheet("填写说明")
    for line in (
        ["单据类型", "填“销售”或“采购”"],
        ["合同编号", "本部门的销售或采购合同编号"],
        ["物料名称", "可写俗称或简称，系统映射为标准物料编码"],
        ["数量", "按合同主计量单位填写，大于 0"],
        ["单价", "含税单价，元；不填会标为异常"],
        ["交期", "日期，格式 2026-12-01，不早于今天且不晚于合同到期日"],
        ["备注", "金额超出合同剩余额度时必填"],
    ):
        note.append(line)
    note.column_dimensions["A"].width = 12
    note.column_dimensions["B"].width = 50
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse(content: bytes) -> list[tuple[int, dict[str, str]]]:
    """返回 [(Excel 行号, 行输入)]；列结构不符或没有数据行时整份拒绝。"""
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, KeyError, OSError, ValueError) as e:
        raise BizError(400, "无法读取 Excel 文件，请上传 .xlsx 格式") from e
    try:
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None) or ()
        index = {_cell(h): i for i, h in enumerate(header) if _cell(h)}
        missing = [h for h in REQUIRED if h not in index]
        if missing:
            raise BizError(400, f"文件不符合导入模板，缺少列：{'、'.join(missing)}")
        out: list[tuple[int, dict[str, str]]] = []
        for row_no, values in enumerate(rows, start=2):
            item = {
                field: _cell(values[index[h]]) if h in index and index[h] < len(values) else ""
                for h, field in FIELDS.items()
            }
            if not any(item.values()):
                continue
            out.append((row_no, item))
            if len(out) > MAX_ROWS:
                raise BizError(400, f"单次最多导入 {MAX_ROWS} 行")
    finally:
        wb.close()
    if not out:
        raise BizError(400, "文件中没有可导入的订单")
    return out


# ---------------------------------------------------------------- 逐行校验

ORDER_TYPES = {"销售": "sales", "销售订单": "sales", "sales": "sales", "采购": "purchase", "采购订单": "purchase", "purchase": "purchase"}


def _decimal(text: str) -> tuple[Decimal | None, bool]:
    """返回 (数值, 是否格式错误)；空值不算格式错误。"""
    text = (text or "").replace(",", "").strip()
    if not text:
        return None, False
    try:
        return Decimal(text), False
    except InvalidOperation:
        return None, True


def _date(text: str) -> tuple[date | None, bool]:
    text = (text or "").strip()
    if not text:
        return None, False
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text[:11].strip(), fmt).date(), False
        except ValueError:
            continue
    return None, True


@dataclass
class RowResult:
    status: str  # ok / over / error
    issues: list[Issue]
    data: DraftData
    contract_id: int | None
    amount: Decimal
    qty: Decimal
    remaining_amount: Decimal | None

    def result_json(self) -> dict[str, Any]:
        item = self.data.items[0] if self.data.items else None
        return {
            "material_code": item.material_code if item else None,
            "material_name": item.material_name if item else "",
            "material_spec": item.spec if item and item.material_code else "",
            "unit": item.unit if item else "",
            "amount": str(item.amount) if item and item.amount is not None else None,
            "candidates": item.candidates if item else [],
            "party_name": self.data.party_name,
            "remaining_amount": str(self.remaining_amount) if self.remaining_amount is not None else None,
            "draft": self.data.model_dump(mode="json"),
        }


async def validate_row(
    session: AsyncSession, user: User, row: dict[str, str], *, today: date, extra_usage: quota.Usage | None
) -> RowResult:
    pre: list[Issue] = []
    order_type = ORDER_TYPES.get((row.get("order_type") or "").strip())
    if order_type is None:
        pre.append(Issue(field="order_type", level="error", message="单据类型应填“销售”或“采购”"))
    qty, qty_bad = _decimal(row.get("quantity", ""))
    if qty_bad:
        pre.append(Issue(field="items.0.quantity", level="error", message="数量不是有效数字"))
    price, price_bad = _decimal(row.get("unit_price", ""))
    if price_bad:
        pre.append(Issue(field="items.0.unit_price", level="error", message="单价不是有效数字"))
    delivery, date_bad = _date(row.get("delivery_date", ""))
    if date_bad:
        pre.append(Issue(field="delivery_date", level="error", message="交期不是有效日期，格式如 2026-12-01"))

    data = DraftData(
        order_type=order_type or "sales",
        contract_no=(row.get("contract_no") or "").strip() or None,
        delivery_date=delivery,
        remark=(row.get("remark") or "").strip(),
        items=[
            DraftItem(
                raw_name=(row.get("raw_name") or "").strip(),
                spec=(row.get("spec") or "").strip(),
                quantity=qty,
                unit_price=price,
                material_code=(row.get("material_code") or "").strip() or None,
            )
        ],
    )
    contract = await draft_validator.find_contract(session, data.contract_no) if data.contract_no else None
    if contract is not None and contract.dept_id != user.dept_id:
        contract = None
    if data.items[0].raw_name or data.items[0].material_code:
        await normalize_items(session, data, contract, None)
    candidates = data.items[0].candidates
    # Excel 是经办人整理好的数据，缺单价作为异常暴露，不自动取合同单价（D-019）
    assembled = await draft_validator.assemble(
        session, user, data, today=today, fill_price_from_contract=False, extra_usage=extra_usage
    )
    if candidates and not assembled.data.items[0].candidates and not assembled.data.items[0].material_code:
        assembled.data.items[0].candidates = candidates

    # 格式错误优先，同一字段只保留一条错误
    seen = {i.field for i in pre}
    issues = pre + [i for i in assembled.issues if not (i.level == "error" and i.field in seen)]
    # 收货地址随合同项目带出，合同错误时不再重复提示
    if any(i.field == "contract_no" for i in issues):
        issues = [i for i in issues if i.field != "address"]
    over = assembled.quota is not None and assembled.quota.over_quota
    if over and not assembled.data.remark:
        # 超额未填备注不能提交：把超额提示改为备注字段上的错误，原因只显示一次
        issues = [
            Issue(field="remark", level="error", message=i.message.replace("提交需填写备注并转待特批", "请在备注中说明原因"))
            if i.level == "over"
            else i
            for i in issues
        ]
    has_error = any(i.level == "error" for i in issues)
    status = "error" if has_error else ("over" if over else "ok")
    q = assembled.quota
    return RowResult(
        status=status,
        issues=issues,
        data=assembled.data,
        contract_id=assembled.contract.id if assembled.contract is not None else None,
        amount=q.current_amount if q else Decimal("0"),
        qty=q.current_qty if q else Decimal("0"),
        remaining_amount=q.remaining_amount if q else None,
    )


async def validate_batch(session: AsyncSession, user: User, batch: ImportBatch, *, today: date) -> None:
    """按行号顺序校验未提交的行；同一合同前面可提交的行占用的额度计入后面行（DESIGN 4.3）。

    已提交行的订单已在数据库中计入合同占用，不再重复累计。
    """
    acc: dict[int, quota.Usage] = {}
    for row in sorted(batch.rows, key=lambda r: r.row_no):
        if row.status == "submitted":
            continue
        inp = dict(row.data.get("input") or {})
        res = await validate_row(session, user, inp, today=today, extra_usage=None)
        if res.contract_id is not None and res.contract_id in acc:
            # 有前面行的占用时按累计额度重算
            res = await validate_row(session, user, inp, today=today, extra_usage=acc[res.contract_id])
        row.data = {"input": inp, "result": res.result_json()}
        row.issues = [i.model_dump() for i in res.issues]
        row.status = res.status
        row.message = "；".join(i.message for i in res.issues if i.level in ("error", "over"))[:255]
        if res.status != "error" and res.contract_id is not None:
            prev = acc.get(res.contract_id, quota.Usage())
            acc[res.contract_id] = quota.Usage(prev.amount + res.amount, prev.qty + res.qty)
    refresh_counts(batch)


def refresh_counts(batch: ImportBatch) -> None:
    batch.total_rows = len(batch.rows)
    batch.success_rows = sum(1 for r in batch.rows if r.status == "submitted")
    batch.failed_rows = sum(1 for r in batch.rows if r.status in ("error", "failed"))
