"""提单压测：在独立库上启动临时后端实例，测量提交、读取、批量导入与对话在不同并发下的延迟、吞吐和结果正确性。

用法（backend 目录）：
    uv run python -m scripts.load_test --levels 1,4,8,16 --orders 40 --batch-rows 500 --chat 12 --out lt.json

各阶段：
1. 提交：每档并发预先保存 N 份草稿（同一合同、各 1 吨），再按并发上限提交，校验单号唯一、每笔都新建订单。
2. 重复提交：20 份草稿各同时发 5 次提交，校验只生成 20 笔订单、同一草稿的 5 次响应单号相同（SC-004）。
3. 额度争抢：40 份草稿同时提交到剩余额度只够 6 笔的采购合同，按单号顺序逐笔复算超额判定（SC-003）。
4. 读取：订单列表、订单详情、合同详情三个接口混合请求，按并发 1/8/32 测延迟。
5. 批量导入：生成 R 行全部合法的 Excel，测上传校验和批量提交耗时，校验成功行数。
6. 对话：调用真实大模型，并发 1 与 4 各发 M 次首轮对话，测单轮响应时间（SC-008）。--chat 0 跳过。
"""
import argparse
import asyncio
import io
import json
import platform
import time
from datetime import date, timedelta
from decimal import Decimal

import httpx
from openpyxl import Workbook

from app.core import clock
from scripts._bench import Timer, instance, login, summary_ms

SALES_CONTRACT = "2026-WZ-089"
HOT_CONTRACT = "2026-CG-031"
CHAT_MESSAGES = [
    "给中建八局科技城项目下 200 吨 HRB400E 螺纹钢，走 2026-WZ-089 合同，后天送到一号工地",
    "下 50 吨三级螺纹16，走 2026-WZ-089 合同，下周三送",
    "新建采购订单，2026-CG-031 合同，42.5 水泥 100 吨，月底到货",
]


def draft_body(contract_no: str, order_type: str, code: str, qty: str, price: str | None, remark: str = "") -> dict:
    return {
        "session_id": f"lt-{time.time_ns()}",
        "draft_id": None,
        "data": {
            "order_type": order_type,
            "contract_no": contract_no,
            "delivery_date": (clock.today() + timedelta(days=3)).isoformat(),
            "remark": remark,
            "items": [{"material_code": code, "quantity": qty, "unit_price": price}],
        },
    }


async def new_drafts(c: httpx.AsyncClient, base: str, h: dict, n: int, body_fn) -> list[str]:
    ids = []
    for _ in range(n):
        r = await c.post(f"{base}/api/drafts", json=body_fn(), headers=h)
        r.raise_for_status()
        ids.append(r.json()["id"])
    return ids


async def run_limited(concurrency: int, coros):
    sem = asyncio.Semaphore(concurrency)

    async def one(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*[one(x) for x in coros])


async def timed(c: httpx.AsyncClient, method: str, url: str, **kw):
    t0 = time.perf_counter()
    r = await c.request(method, url, **kw)
    return time.perf_counter() - t0, r


# ---------- 各阶段 ----------


async def phase_submit(c, base, h, levels: list[int], n: int) -> list[dict]:
    rows = []
    for level in levels:
        ids = await new_drafts(c, base, h, n, lambda: draft_body(SALES_CONTRACT, "sales", "STL-RB-400E-20", "1", None))
        with Timer() as t:
            res = await run_limited(level, [timed(c, "POST", f"{base}/api/drafts/{i}/submit", json={"remark": ""}, headers=h) for i in ids])
        lat = [x[0] for x in res]
        bodies = [x[1].json() for x in res if x[1].status_code == 200]
        errors = [x[1].status_code for x in res if x[1].status_code != 200]
        nos = [b["order_no"] for b in bodies]
        rows.append({
            "concurrency": level,
            "requests": n,
            "ok": len(bodies),
            "errors": errors,
            "unique_order_no": len(set(nos)) == len(nos) == n,
            "all_created": all(b["created"] for b in bodies),
            "wall_s": round(t.elapsed, 2),
            "throughput_per_s": round(n / t.elapsed, 1),
            "latency_ms": summary_ms(lat),
        })
        print(f"[提交] 并发 {level}: {rows[-1]}")
    return rows


async def phase_duplicate(c, base, h, drafts: int = 20, repeat: int = 5) -> dict:
    ids = await new_drafts(c, base, h, drafts, lambda: draft_body(SALES_CONTRACT, "sales", "STL-RB-400E-20", "1", None))
    calls = [timed(c, "POST", f"{base}/api/drafts/{i}/submit", json={"remark": ""}, headers=h) for i in ids for _ in range(repeat)]
    with Timer() as t:
        res = await asyncio.gather(*calls)
    per_draft: dict[str, set] = {}
    created = 0
    errors = []
    for (lat, r), draft_id in zip(res, [i for i in ids for _ in range(repeat)]):
        if r.status_code != 200:
            errors.append(r.status_code)
            continue
        per_draft.setdefault(draft_id, set()).add(r.json()["order_no"])
        created += int(r.json()["created"])
    out = {
        "drafts": drafts,
        "requests": len(calls),
        "errors": errors,
        "orders_created": created,
        "same_no_per_draft": all(len(v) == 1 for v in per_draft.values()) and len(per_draft) == drafts,
        "wall_s": round(t.elapsed, 2),
        "latency_ms": summary_ms([x[0] for x in res]),
    }
    print(f"[重复提交] {out}")
    return out


async def phase_contention(c, base, h, n: int = 40) -> dict:
    before = (await c.get(f"{base}/api/master/contracts/{HOT_CONTRACT}", headers=h)).json()["quota"]
    remaining0 = Decimal(str(before["remaining_amount"]))
    ids = await new_drafts(c, base, h, n, lambda: draft_body(HOT_CONTRACT, "purchase", "CEM-PO-425", "50", "440", remark="压测：额度争抢"))
    with Timer() as t:
        res = await asyncio.gather(*[timed(c, "POST", f"{base}/api/drafts/{i}/submit", json={"remark": "压测：额度争抢"}, headers=h) for i in ids])
    bodies = [r.json() for _, r in res if r.status_code == 200]
    detail = {b["order_no"]: (await c.get(f"{base}/api/orders/{b['order_id']}", headers=h)).json() for b in bodies}
    # 单号流水即提交先后，按单号顺序逐笔复算：本单金额大于剩余额度才算超额
    remaining = remaining0
    mismatch = []
    for no in sorted(detail):
        o = detail[no]
        amount = Decimal(str(o["total_amount"]))
        expect_over = amount > remaining
        if bool(o["over_quota"]) != expect_over or o["status"] != ("pending_special" if expect_over else "submitted"):
            mismatch.append(no)
        remaining -= amount
    not_over = sum(1 for o in detail.values() if not o["over_quota"])
    out = {
        "requests": n,
        "ok": len(bodies),
        "errors": [r.status_code for _, r in res if r.status_code != 200],
        "remaining_before": str(remaining0),
        "amount_each": "22000.00",
        "expected_not_over": int(remaining0 // Decimal("22000")),
        "not_over": not_over,
        "mismatch": mismatch,
        "wall_s": round(t.elapsed, 2),
        "latency_ms": summary_ms([x[0] for x in res]),
    }
    print(f"[额度争抢] {out}")
    return out


async def phase_reads(c, base, h, levels: list[int], total: int = 300) -> list[dict]:
    orders = (await c.get(f"{base}/api/orders", params={"order_type": "sales", "page_size": 20}, headers=h)).json()["items"]
    targets = [
        ("GET", f"{base}/api/orders", {"params": {"order_type": "sales", "page": 1, "page_size": 20}}),
        ("GET", f"{base}/api/orders/{orders[0]['id']}", {}),
        ("GET", f"{base}/api/master/contracts/{SALES_CONTRACT}", {}),
    ]
    rows = []
    for level in levels:
        calls = [timed(c, targets[i % 3][0], targets[i % 3][1], headers=h, **targets[i % 3][2]) for i in range(total)]
        with Timer() as t:
            res = await run_limited(level, calls)
        by = {name: [] for name in ("list", "detail", "contract")}
        for i, (lat, _) in enumerate(res):
            by[("list", "detail", "contract")[i % 3]].append(lat)
        rows.append({
            "concurrency": level,
            "requests": total,
            "errors": sum(1 for _, r in res if r.status_code != 200),
            "rps": round(total / t.elapsed, 1),
            "all_ms": summary_ms([x[0] for x in res]),
            **{f"{k}_ms": summary_ms(v) for k, v in by.items()},
        })
        print(f"[读取] 并发 {level}: rps {rows[-1]['rps']} all {rows[-1]['all_ms']}")
    return rows


def batch_excel(rows: int, today: date) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["单据类型", "合同编号", "物料名称", "规格", "数量", "单价", "交期", "备注"])
    mats = [("螺纹钢20", 3650), ("三级螺纹16", 3680), ("25螺", 3620)]
    for i in range(rows):
        name, price = mats[i % 3]
        ws.append(["销售", SALES_CONTRACT, name, "HRB400E", 1, price, today + timedelta(days=5), ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def phase_batch(c, base, h, rows: int) -> dict:
    content = batch_excel(rows, clock.today())
    files = {"file": ("loadtest.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    with Timer() as t_up:
        r = await c.post(f"{base}/api/batch", files=files, headers=h, timeout=600)
    r.raise_for_status()
    view = r.json()
    statuses = {}
    for row in view["rows"]:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    with Timer() as t_sub:
        r2 = await c.post(f"{base}/api/batch/{view['id']}/submit", headers=h, timeout=600)
    r2.raise_for_status()
    done = r2.json()
    out = {
        "rows": rows,
        "upload_validate_s": round(t_up.elapsed, 2),
        "row_status_after_validate": statuses,
        "submit_s": round(t_sub.elapsed, 2),
        "success_rows": done["success_rows"],
        "failed_rows": done["failed_rows"],
        "rows_per_s_submit": round(done["success_rows"] / t_sub.elapsed, 1),
    }
    print(f"[批量导入] {out}")
    return out


async def phase_chat(c, base, h, levels: list[int], n: int) -> list[dict]:
    rows = []
    for level in levels:
        calls = [
            timed(c, "POST", f"{base}/api/chat",
                  json={"session_id": f"lt-chat-{time.time_ns()}-{i}", "draft_id": None, "message": CHAT_MESSAGES[i % 3]},
                  headers=h, timeout=120)
            for i in range(n)
        ]
        with Timer() as t:
            res = await run_limited(level, calls)
        failed = sum(1 for _, r in res if r.status_code != 200 or r.json().get("failed"))
        rows.append({
            "concurrency": level,
            "requests": n,
            "failed": failed,
            "wall_s": round(t.elapsed, 2),
            "latency_ms": summary_ms([x[0] for x in res]),
            "within_15s": sum(1 for lat, _ in res if lat <= 15),
        })
        print(f"[对话] 并发 {level}: {rows[-1]}")
    return rows


async def main(args) -> None:
    levels = [int(x) for x in args.levels.split(",")]
    result = {
        "date": clock.today().isoformat(),
        "env": {"python": platform.python_version(), "os": platform.platform(), "processor": platform.processor()},
        "args": vars(args),
    }
    async with instance("trade_order_loadtest", keep_db=args.keep_db) as (base, _):
        limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
        async with httpx.AsyncClient(timeout=60, limits=limits) as c:
            h = await login(c, base, "jbr01")
            result["submit"] = await phase_submit(c, base, h, levels, args.orders)
            result["duplicate"] = await phase_duplicate(c, base, h)
            result["contention"] = await phase_contention(c, base, h)
            result["reads"] = await phase_reads(c, base, h, [1, 8, 32])
            if args.batch_rows:
                result["batch"] = await phase_batch(c, base, h, args.batch_rows)
            if args.chat:
                result["chat"] = await phase_chat(c, base, h, [1, 4], args.chat)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print("结果已写入", args.out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--levels", default="1,4,8,16", help="提交阶段的并发档位")
    p.add_argument("--orders", type=int, default=40, help="每档提交的订单数")
    p.add_argument("--batch-rows", type=int, default=500, help="批量导入行数，0 跳过")
    p.add_argument("--chat", type=int, default=12, help="每档对话请求数，0 跳过（调用真实大模型）")
    p.add_argument("--out", default="", help="结果 JSON 路径")
    p.add_argument("--keep-db", action="store_true", help="结束后保留压测库 trade_order_loadtest")
    asyncio.run(main(p.parse_args()))
