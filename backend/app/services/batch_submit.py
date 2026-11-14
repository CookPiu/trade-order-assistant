"""Excel 批量提交（FR-036、DESIGN 4.3）：每行一个事务独立成单，单行失败不影响其他行。

不同合同的行并发提交；同一合同的行按行号顺序串行提交，保证超额判定与校验时的批内累计一致。
"""
import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import BizError
from app.models import Draft, ImportBatch, User
from app.schemas import DraftData
from app.services import draft_validator, order_flow

log = logging.getLogger(__name__)
CONCURRENCY = 4
SUBMITTABLE = ("ok", "over")


@dataclass
class RowOutcome:
    row_id: int
    ok: bool
    order_no: str | None
    order_status: str | None
    message: str


async def _submit_row(maker: async_sessionmaker[AsyncSession], user_id: int, batch_id: int, row_id: int, data: DraftData) -> RowOutcome:
    async with maker() as s:
        try:
            user = await s.get(User, user_id)
            assert user is not None
            assembled = await draft_validator.assemble(s, user, data, fill_price_from_contract=False)
            draft = Draft(
                id=str(uuid.uuid4()),
                session_id=f"batch-{batch_id}",
                user_id=user.id,
                dept_id=user.dept_id,
                order_type=assembled.data.order_type,
                data=assembled.data.model_dump(mode="json"),
                issues=[i.model_dump() for i in assembled.issues],
                status=assembled.status,
            )
            s.add(draft)
            await s.commit()
            order, _ = await order_flow.submit_with_retry(s, user, draft.id, data.remark, source="excel")
            return RowOutcome(row_id, True, order.order_no, order.status, "")
        except BizError as e:
            await s.rollback()
            reasons = [i.get("message", "") for i in (e.detail or []) if isinstance(i, dict)]
            msg = e.message + (f"：{'；'.join(reasons)}" if reasons else "")
            return RowOutcome(row_id, False, None, None, msg[:255])
        except Exception:  # noqa: BLE001
            await s.rollback()
            log.exception("batch row submit failed: batch=%s row=%s", batch_id, row_id)
            return RowOutcome(row_id, False, None, None, "提交时发生系统错误，请稍后重试")


async def submit_rows(
    maker: async_sessionmaker[AsyncSession], user_id: int, batch: ImportBatch
) -> dict[int, RowOutcome]:
    groups: dict[str, list] = defaultdict(list)
    for row in sorted(batch.rows, key=lambda r: r.row_no):
        if row.status in SUBMITTABLE:
            draft = (row.data.get("result") or {}).get("draft") or {}
            groups[draft.get("contract_no") or f"row-{row.id}"].append((row.id, DraftData.model_validate(draft)))

    sem = asyncio.Semaphore(CONCURRENCY)
    outcomes: dict[int, RowOutcome] = {}

    async def run_group(rows):
        async with sem:
            for row_id, data in rows:
                outcomes[row_id] = await _submit_row(maker, user_id, batch.id, row_id, data)

    await asyncio.gather(*(run_group(rows) for rows in groups.values()))
    return outcomes
