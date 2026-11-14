"""识别质量评估：物料标准化、对话抽取、单据图片识别。在独立库上启动临时后端实例，不影响业务库。

用法（backend 目录）：
    uv run python -m scripts.eval_quality --out eval.json
    uv run python -m scripts.eval_quality --skip-llm      # 只跑物料标准化，不调用大模型

1. 物料标准化：示例数据中的全部别名、“名称 + 规格”和物料编码本身各映射一次，比对期望编码；规则分不出的
   候选再交给模型挑选（与正式流程相同，--skip-llm 时跳过）；另取字典外物资，确认不会返回任何编码（C-002）。
2. 对话抽取（DeepSeek）：20 条不同说法的首轮提单语句，经 /api/chat 生成草稿，逐字段比对单据类型、合同号、
   物料编码与数量、交期、单价（语句给出单价时）。相对日期以运行当天为基准换算期望值。
3. 图片识别（百炼视觉模型）：样例发货签收单原图与四种画质变体，经 /api/ocr 识别，比对合同号、物料编码、数量和金额。
"""
import argparse
import asyncio
import io
import json
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import clock
from app.models import Material, MaterialAlias
from app.graph.nodes import llm_picker
from app.services.material_normalizer import normalize
from scripts._bench import BACKEND_DIR, instance, login, summary_ms

SAMPLE = BACKEND_DIR.parent / "samples" / "发货签收单_42.5水泥.jpg"
OUTSIDE = ["铝合金门窗", "PVC 排水管 DN110", "镀锌钢管 DN50", "防水卷材 SBS", "电缆 YJV 3×95"]


def next_weekday(today: date, weekday: int, weeks_ahead: int = 0) -> date:
    """下周 X：下一个自然周的周 X（weekday 0 为周一），与 date_phrase 的规则一致。"""
    monday_next = today + timedelta(days=7 - today.weekday())
    return monday_next + timedelta(days=weekday + 7 * weeks_ahead)


def coming_weekday(today: date, weekday: int) -> date:
    """周 X：今天之后最近的周 X。"""
    return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)


def month_end(today: date) -> date:
    first_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first_next - timedelta(days=1)


def chat_cases(today: date) -> list[dict]:
    d = lambda n: today + timedelta(days=n)  # noqa: E731
    y = today.year
    return [
        {"text": "给中建八局科技城项目下 200 吨 HRB400E 螺纹钢，走 2026-WZ-089 合同，后天送到一号工地",
         "type": "sales", "contract": "2026-WZ-089", "items": {"STL-RB-400E-20": 200}, "date": d(2)},
        {"text": "下 50 吨三级螺纹16，走 2026-WZ-089 合同，下周三送",
         "type": "sales", "contract": "2026-WZ-089", "items": {"STL-RB-400E-16": 50}, "date": next_weekday(today, 2)},
        {"text": "新建采购订单，2026-CG-031 合同，42.5 水泥 100 吨，月底到货",
         "type": "purchase", "contract": "2026-CG-031", "items": {"CEM-PO-425": 100}, "date": month_end(today)},
        {"text": "2026-WZ-089 要 30 吨 25 的螺纹钢，11月20日送到",
         "type": "sales", "contract": "2026-WZ-089", "items": {"STL-RB-400E-25": 30}, "date": date(y, 11, 20)},
        {"text": "合同 2026-CG-040 采购 HRB400E Φ16 螺纹钢 80 吨，3天内到",
         "type": "purchase", "contract": "2026-CG-040", "items": {"STL-RB-400E-16": 80}, "date": d(3)},
        {"text": "走2026-WZ-095，28螺 20吨，明天送",
         "type": "sales", "contract": "2026-WZ-095", "items": {"STL-RB-400E-28": 20}, "date": d(1)},
        {"text": "2026-CG-031 进 52.5 水泥 60 吨，下周一到",
         "type": "purchase", "contract": "2026-CG-031", "items": {"CEM-PO-525": 60}, "date": next_weekday(today, 0)},
        {"text": "2026-WZ-089 合同，Φ20 螺纹 一百吨，大后天送",
         "type": "sales", "contract": "2026-WZ-089", "items": {"STL-RB-400E-20": 100}, "date": d(3)},
        {"text": "采购：2026-CG-040，三级钢20 一百二十吨，12月1日到货",
         "type": "purchase", "contract": "2026-CG-040", "items": {"STL-RB-400E-20": 120}, "date": date(y, 12, 1)},
        {"text": "销售订单，合同2026-WZ-089，16螺 45 吨、25螺 15 吨，后天送一号工地",
         "type": "sales", "contract": "2026-WZ-089", "items": {"STL-RB-400E-16": 45, "STL-RB-400E-25": 15}, "date": d(2)},
        {"text": "2026-WZ-095 合同下 HRB400E 25 的 10 吨，11/18 送",
         "type": "sales", "contract": "2026-WZ-095", "items": {"STL-RB-400E-25": 10}, "date": date(y, 11, 18)},
        {"text": "2026-CG-031 补 P.O42.5 散装水泥 200 吨，周三到",
         "type": "purchase", "contract": "2026-CG-031", "items": {"CEM-PO-425": 200}, "date": coming_weekday(today, 2)},
        {"text": "给科技城项目再发 20 吨 Φ25 螺纹钢，合同 2026-WZ-089，下周五",
         "type": "sales", "contract": "2026-WZ-089", "items": {"STL-RB-400E-25": 20}, "date": next_weekday(today, 4)},
        {"text": "2026-CG-040，螺纹钢 HRB400E 20mm 300 吨，月底",
         "type": "purchase", "contract": "2026-CG-040", "items": {"STL-RB-400E-20": 300}, "date": month_end(today)},
        {"text": "合同号2026-WZ-089，HRB400E螺纹钢16，数量 12.5 吨，后天",
         "type": "sales", "contract": "2026-WZ-089", "items": {"STL-RB-400E-16": 12.5}, "date": d(2)},
        {"text": "2026-WZ-095 的 28 螺纹钢 5 吨，11月22日送",
         "type": "sales", "contract": "2026-WZ-095", "items": {"STL-RB-400E-28": 5}, "date": date(y, 11, 22)},
        {"text": "采购 2026-CG-031，四二五水泥 80 吨，单价 445，明天到",
         "type": "purchase", "contract": "2026-CG-031", "items": {"CEM-PO-425": 80}, "date": d(1), "price": 445},
        {"text": "2026-WZ-089 下 60 吨螺纹钢20，单价 3600，后天",
         "type": "sales", "contract": "2026-WZ-089", "items": {"STL-RB-400E-20": 60}, "date": d(2), "price": 3600},
        {"text": "帮我下个单：2026-CG-040 合同，三级螺纹16 二十吨，下下周一",
         "type": "purchase", "contract": "2026-CG-040", "items": {"STL-RB-400E-16": 20}, "date": next_weekday(today, 0, 1)},
        {"text": "2026-WZ-089，200吨 HRB400E Φ20，交期 2026-11-25",
         "type": "sales", "contract": "2026-WZ-089", "items": {"STL-RB-400E-20": 200}, "date": date(2026, 11, 25)},
    ]


# ---------- 1. 物料标准化 ----------


async def eval_normalizer(db_url, use_llm: bool) -> dict:
    engine = create_async_engine(db_url)
    groups: dict[str, dict] = {}
    async with AsyncSession(engine) as s:
        codes = set((await s.execute(select(Material.code))).scalars().all())
        aliases = (await s.execute(select(MaterialAlias.alias, MaterialAlias.material_code))).all()
        mats = (await s.execute(select(Material))).scalars().all()
        cases = (
            [("alias", a, "", c) for a, c in aliases]
            + [("name_spec", m.name, m.spec, m.code) for m in mats]
            + [("code", m.code, "", m.code) for m in mats]
        )
        outside_codes = []
        for kind, raw, spec, expect in cases:
            m = await normalize(s, raw, spec)
            g = groups.setdefault(kind, {"total": 0, "correct": 0, "wrong": []})
            g["total"] += 1
            if m.code == expect:
                g["correct"] += 1
            else:
                g["wrong"].append({"raw": raw, "spec": spec, "expect": expect, "got": m.code, "method": m.method,
                                   "candidates": [x["code"] for x in m.candidates]})
            if m.code is not None and m.code not in codes:
                outside_codes.append(m.code)
        # 规则无法区分的候选在正式流程中交给模型挑选，返回值必须属于候选
        picked = []
        if use_llm:
            for g in groups.values():
                for w in g["wrong"]:
                    m = await normalize(s, w["raw"], w["spec"], picker=llm_picker(s))
                    w["with_picker"] = m.code
                    picked.append(m.code == w["expect"])
        negatives = []
        for raw in OUTSIDE:
            m = await normalize(s, raw)
            negatives.append({"input": raw, "got": m.code, "method": m.method})
            if m.code is not None and m.code not in codes:
                outside_codes.append(m.code)
    await engine.dispose()
    out = {
        "groups": groups,
        "outside_dictionary_codes": outside_codes,
        "negatives": negatives,
        "negatives_no_code": sum(1 for n in negatives if n["got"] is None),
        "picker_fixed": f"{sum(picked)}/{len(picked)}" if use_llm else "skipped",
    }
    print("[物料标准化]", {k: f"{v['correct']}/{v['total']}" for k, v in groups.items()},
          "模型挑选后补正", out["picker_fixed"], "字典外编码", len(outside_codes), "字典外物资未给编码", f"{out['negatives_no_code']}/{len(OUTSIDE)}")
    return out


# ---------- 2. 对话抽取 ----------


def _num(v) -> float | None:
    return None if v in (None, "") else float(Decimal(str(v)))


async def eval_chat(c: httpx.AsyncClient, base: str, h: dict, today: date) -> dict:
    fields = {"type": 0, "contract": 0, "items": 0, "date": 0, "price": 0}
    price_total = 0
    details = []
    lat = []
    for i, case in enumerate(chat_cases(today), 1):
        t0 = time.perf_counter()
        r = await c.post(f"{base}/api/chat", json={"session_id": f"eval-{time.time_ns()}", "draft_id": None, "message": case["text"]},
                         headers=h, timeout=120)
        lat.append(time.perf_counter() - t0)
        body = r.json()
        d = (body.get("draft") or {}).get("data") or {}
        got_items = {it.get("material_code"): _num(it.get("quantity")) for it in d.get("items", [])}
        ok = {
            "type": d.get("order_type") == case["type"],
            "contract": d.get("contract_no") == case["contract"],
            "items": got_items == {k: float(v) for k, v in case["items"].items()},
            "date": d.get("delivery_date") == case["date"].isoformat(),
        }
        if "price" in case:
            price_total += 1
            prices = [_num(it.get("unit_price")) for it in d.get("items", [])]
            ok["price"] = prices == [float(case["price"])]
        for k, v in ok.items():
            fields[k] += int(v)
        all_ok = all(ok.values())
        details.append({
            "no": i, "text": case["text"], "ok": all_ok, "fields": ok,
            "got": {"type": d.get("order_type"), "contract": d.get("contract_no"), "items": got_items, "date": d.get("delivery_date")},
            "expect": {"type": case["type"], "contract": case["contract"], "items": case["items"], "date": case["date"].isoformat()},
            "latency_s": round(lat[-1], 2),
        })
        print(f"[对话抽取] {i:02d} {'通过' if all_ok else '未通过'} {ok if not all_ok else ''}")
    n = len(details)
    return {
        "cases": n,
        "all_fields_correct": sum(1 for x in details if x["ok"]),
        "field_correct": {**{k: f"{v}/{n}" for k, v in fields.items() if k != "price"}, "price": f"{fields['price']}/{price_total}"},
        "latency_ms": summary_ms(lat),
        "details": details,
    }


# ---------- 3. 图片识别 ----------


def image_variants() -> dict[str, bytes]:
    src = Image.open(SAMPLE).convert("RGB")

    def jpg(img: Image.Image, q: int = 88) -> bytes:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q)
        return buf.getvalue()

    w, h = src.size
    return {
        "原图": SAMPLE.read_bytes(),
        "缩小一半": jpg(src.resize((w // 2, h // 2))),
        "JPEG 质量 30": jpg(src, 30),
        "旋转 5 度": jpg(src.rotate(5, expand=True, fillcolor=(90, 90, 90))),
        "灰度": jpg(src.convert("L").convert("RGB")),
    }


async def eval_ocr(c: httpx.AsyncClient, base: str, h: dict) -> dict:
    rows = []
    lat = []
    for name, raw in image_variants().items():
        t0 = time.perf_counter()
        r = await c.post(f"{base}/api/ocr", files={"file": ("receipt.jpg", raw, "image/jpeg")}, headers=h, timeout=180)
        lat.append(time.perf_counter() - t0)
        if r.status_code != 200:
            rows.append({"variant": name, "status": r.status_code, "ok": False, "latency_s": round(lat[-1], 2)})
            continue
        body = r.json()
        items = body["data"]["items"]
        card = body["card"]
        it = items[0] if items else {}
        ok = {
            "contract": body["data"].get("contract_no") == "2026-CG-031",
            "material": len(items) == 1 and it.get("material_code") == "CEM-PO-425",
            "quantity": _num(it.get("quantity")) == 500.0,
            "amount": _num(it.get("amount")) == 220000.0,
        }
        rows.append({"variant": name, "ok": all(ok.values()), "fields": ok, "latency_s": round(lat[-1], 2),
                     "card_items": card.get("items") if isinstance(card, dict) else card})
        print(f"[图片识别] {name}: {'通过' if all(ok.values()) else ok}")
    return {"variants": len(rows), "all_correct": sum(1 for x in rows if x["ok"]), "latency_ms": summary_ms(lat), "details": rows}


async def main(args) -> None:
    today = clock.today()
    result = {"date": today.isoformat()}
    async with instance("trade_order_eval") as (base, db_url):
        result["normalizer"] = await eval_normalizer(db_url, not args.skip_llm)
        if not args.skip_llm:
            async with httpx.AsyncClient(timeout=120) as c:
                h = await login(c, base, "jbr01")
                result["chat"] = await eval_chat(c, base, h, today)
                result["ocr"] = await eval_ocr(c, base, h)
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("结果已写入", args.out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="", help="结果 JSON 路径")
    p.add_argument("--skip-llm", action="store_true", help="只跑物料标准化")
    asyncio.run(main(p.parse_args()))
