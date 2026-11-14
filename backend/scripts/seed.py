"""初始化脚本：建库、建表并灌入示例数据，可重复执行（FR-061）。

用法（在 backend 目录）：uv run python -m scripts.seed
示例账号均为本地演示用测试账号，密码见 DEMO_PASSWORD。
"""
import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import clock
from app.core.config import get_settings
from app.core.security import hash_password
from app.models import (
    APPROVED,
    PURCHASE,
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_OPERATOR,
    SALES,
    Base,
    Contract,
    ContractItem,
    Dept,
    Draft,
    Material,
    MaterialAlias,
    Order,
    OrderItem,
    Party,
    Project,
    SystemParam,
    User,
)
from app.services import params, trade_sync

DEMO_PASSWORD = "Demo@2026"

DEPTS = [("WZGS", "物资贸易公司"), ("JCGS", "建材贸易公司")]

USERS = [
    # 用户名, 姓名, 角色, 部门代码
    ("jbr01", "张经办", ROLE_OPERATOR, "WZGS"),
    ("spr01", "李审批", ROLE_APPROVER, "WZGS"),
    ("admin", "王管理", ROLE_ADMIN, "WZGS"),
    ("jbr02", "赵经办", ROLE_OPERATOR, "JCGS"),
    ("spr02", "钱审批", ROLE_APPROVER, "JCGS"),
]

PARTIES = [
    ("中建八局第三建设有限公司", "customer"),
    ("城投路桥建设有限公司", "customer"),
    ("华东建材供应有限公司", "supplier"),
    ("江南钢铁销售有限公司", "supplier"),
]

PROJECTS = [
    # 名称, 地址, 联系人, 电话
    ("科技城项目", "科技城大道 88 号一号工地", "陈工", "13800000001"),
    ("滨江大桥项目", "滨江路与沿江大道交叉口东侧", "周工", "13800000002"),
    ("城东安置房项目", "城东新区安置房三标段", "吴工", "13800000003"),
]


def _materials() -> list[tuple[str, str, str, str, str, str, Decimal, list[str]]]:
    """(编码, 名称, 规格, 单位, 品牌, 类别, 公允价, 别名)"""
    rows = []
    for d in (12, 14, 16, 18, 20, 22, 25, 28, 32):
        code = f"STL-RB-400E-{d}"
        aliases = [f"螺纹钢{d}", f"三级螺纹{d}", f"三级钢{d}", f"HRB400E{d}", f"HRB400E螺纹钢{d}", f"Φ{d}螺纹", f"{d}螺"]
        rows.append((code, "热轧带肋钢筋", f"HRB400E Φ{d}", "吨", "江南钢铁", "螺纹钢", Decimal("3600"), aliases))
    for d in (20, 25):
        rows.append(
            (f"STL-RB-500E-{d}", "热轧带肋钢筋", f"HRB500E Φ{d}", "吨", "江南钢铁", "螺纹钢", Decimal("3850"),
             [f"四级螺纹{d}", f"四级钢{d}", f"HRB500E{d}"])
        )
    for d in (8, 10):
        rows.append(
            (f"STL-CR-400E-{d:02d}", "盘螺", f"HRB400E Φ{d}", "吨", "江南钢铁", "盘螺", Decimal("3750"),
             [f"盘螺{d}", f"{d}盘螺", f"三级盘螺{d}"])
        )
    for d, s in ((6.5, "6.5"), (8, "8")):
        rows.append(
            (f"STL-WR-300-{s}", "热轧光圆盘条", f"HPB300 Φ{s}", "吨", "江南钢铁", "线材", Decimal("3700"),
             [f"线材{s}", f"圆钢{s}", f"高线{s}"])
        )
    for t in (10, 20):
        rows.append(
            (f"STL-PL-235-{t}", "热轧钢板", f"Q235B {t}mm", "吨", "江南钢铁", "板材", Decimal("3900"),
             [f"{t}个厚钢板", f"Q235钢板{t}", f"中板{t}"])
        )
    rows += [
        ("STL-HB-400", "热轧H型钢", "HN400×200", "吨", "江南钢铁", "型钢", Decimal("3950"), ["H型钢400", "400H钢"]),
        ("STL-IB-25", "热轧工字钢", "25a", "吨", "江南钢铁", "型钢", Decimal("3900"), ["工字钢25", "25工字钢"]),
        ("STL-AN-50", "热轧等边角钢", "L50×5", "吨", "江南钢铁", "型钢", Decimal("3880"), ["角钢50", "5号角钢"]),
        ("CEM-PO-425", "普通硅酸盐水泥", "P.O 42.5", "吨", "华东建材", "水泥", Decimal("430"),
         ["42.5水泥", "425水泥", "普硅42.5", "PO42.5", "P.O42.5", "四二五水泥"]),
        ("CEM-PO-525", "普通硅酸盐水泥", "P.O 52.5", "吨", "华东建材", "水泥", Decimal("480"),
         ["52.5水泥", "525水泥", "普硅52.5", "PO52.5"]),
        ("CEM-PC-325", "复合硅酸盐水泥", "P.C 32.5", "吨", "华东建材", "水泥", Decimal("380"),
         ["32.5水泥", "325水泥", "复合32.5", "PC32.5"]),
        ("AGG-SD-M", "建筑用砂", "中砂", "吨", "", "砂石", Decimal("110"), ["中砂", "黄砂", "河砂"]),
        ("AGG-GR-525", "建筑用碎石", "5-25mm", "吨", "", "砂石", Decimal("95"), ["碎石", "石子", "5-25碎石", "瓜子片"]),
        ("CON-C30", "商品混凝土", "C30", "立方米", "", "混凝土", Decimal("420"), ["C30混凝土", "C30商混", "30砼"]),
        ("CON-C35", "商品混凝土", "C35", "立方米", "", "混凝土", Decimal("440"), ["C35混凝土", "C35商混", "35砼"]),
    ]
    return rows


def _contracts(today: date) -> list[dict]:
    return [
        {
            "contract_no": "2026-WZ-089", "type": SALES, "party": "中建八局第三建设有限公司", "project": "科技城项目",
            "dept": "WZGS", "total_amount": Decimal("5000000"), "total_qty": Decimal("1400"), "unit": "吨",
            "sign_date": date(2026, 1, 15), "expire_date": date(2027, 6, 30),
            "items": [("STL-RB-400E-20", "3650", "800"), ("STL-RB-400E-16", "3680", "300"),
                      ("STL-RB-400E-25", "3620", "300")],
        },
        {
            # 已有一笔 85 万元的历史订单，剩余可下金额 15 万元（需求场景二）
            "contract_no": "2026-CG-031", "type": PURCHASE, "party": "华东建材供应有限公司", "project": "科技城项目",
            "dept": "WZGS", "total_amount": Decimal("1000000"), "total_qty": Decimal("3000"), "unit": "吨",
            "sign_date": date(2026, 3, 1), "expire_date": date(2027, 3, 31),
            "items": [("CEM-PO-425", "440", "2000"), ("CEM-PO-525", "490", "400")],
            "history": [("CEM-PO-425", "425", "2000")],
        },
        {
            # 临近到期，用于演示交期晚于合同到期日
            "contract_no": "2026-WZ-095", "type": SALES, "party": "城投路桥建设有限公司", "project": "滨江大桥项目",
            "dept": "WZGS", "total_amount": Decimal("2000000"), "total_qty": Decimal("500"), "unit": "吨",
            "sign_date": date(2026, 2, 10), "expire_date": today + timedelta(days=10),
            "items": [("STL-RB-400E-25", "3630", "300"), ("STL-RB-400E-28", "3640", "200")],
        },
        {
            "contract_no": "2026-CG-040", "type": PURCHASE, "party": "江南钢铁销售有限公司", "project": "科技城项目",
            "dept": "WZGS", "total_amount": Decimal("8000000"), "total_qty": Decimal("2200"), "unit": "吨",
            "sign_date": date(2026, 4, 1), "expire_date": date(2027, 12, 31),
            "items": [("STL-RB-400E-20", "3550", "1200"), ("STL-RB-400E-16", "3570", "1000")],
        },
        {
            # 另一部门的合同，用于权限隔离验证
            "contract_no": "2026-JC-012", "type": SALES, "party": "城投路桥建设有限公司", "project": "城东安置房项目",
            "dept": "JCGS", "total_amount": Decimal("3000000"), "total_qty": Decimal("7000"), "unit": "吨",
            "sign_date": date(2026, 5, 1), "expire_date": date(2027, 5, 31),
            "items": [("CEM-PO-425", "450", "7000")],
        },
    ]


async def _get_or_create(session: AsyncSession, model, where: dict, values: dict | None = None):
    stmt = select(model).filter_by(**where)
    obj = (await session.execute(stmt)).unique().scalar_one_or_none()
    if obj is None:
        obj = model(**where, **(values or {}))
        session.add(obj)
        await session.flush()
    return obj


async def seed(session: AsyncSession, today: date | None = None) -> None:
    today = today or clock.today()
    depts = {}
    for code, name in DEPTS:
        depts[code] = await _get_or_create(session, Dept, {"code": code}, {"name": name})
    users = {}
    for username, display, role, dept in USERS:
        users[username] = await _get_or_create(
            session, User, {"username": username},
            {"display_name": display, "role": role, "dept_id": depts[dept].id, "password_hash": hash_password(DEMO_PASSWORD)},
        )
    parties = {n: await _get_or_create(session, Party, {"name": n}, {"kind": k}) for n, k in PARTIES}
    projects = {
        n: await _get_or_create(session, Project, {"name": n}, {"address": a, "contact": c, "phone": p})
        for n, a, c, p in PROJECTS
    }
    for code, name, spec, unit, brand, cat, fair, aliases in _materials():
        await _get_or_create(
            session, Material, {"code": code},
            {"name": name, "spec": spec, "unit": unit, "brand": brand, "category": cat, "fair_price": fair},
        )
        for a in aliases:
            await _get_or_create(session, MaterialAlias, {"alias": a}, {"material_code": code})
    for key, value in params.DEFAULTS.items():
        await _get_or_create(session, SystemParam, {"key": key}, {"value": value, "description": params.DESCRIPTIONS[key]})

    for c in _contracts(today):
        contract = (
            await session.execute(select(Contract).where(Contract.contract_no == c["contract_no"]))
        ).unique().scalar_one_or_none()
        if contract is not None:
            continue
        contract = Contract(
            contract_no=c["contract_no"], contract_type=c["type"], party_id=parties[c["party"]].id,
            project_id=projects[c["project"]].id, dept_id=depts[c["dept"]].id, total_amount=c["total_amount"],
            total_qty=c["total_qty"], unit=c["unit"], sign_date=c["sign_date"], expire_date=c["expire_date"],
        )
        session.add(contract)
        await session.flush()
        for code, price, qty in c["items"]:
            session.add(ContractItem(contract_id=contract.id, material_code=code, unit_price=Decimal(price), quantity=Decimal(qty)))
        await session.flush()
        for idx, (code, price, qty) in enumerate(c.get("history", []), start=1):
            await _history_order(session, contract, users["jbr01"], depts[c["dept"]], projects[c["project"]],
                                 parties[c["party"]], code, Decimal(price), Decimal(qty), idx)
    await session.commit()


async def _history_order(session, contract, user, dept, project, party, code, price, qty, idx) -> None:
    """为合同造一笔已审核的历史订单，使其累计已下金额符合演示需要。"""
    material = await session.get(Material, code)
    amount = (price * qty).quantize(Decimal("0.01"))
    day = contract.sign_date + timedelta(days=30)
    prefix = "XSDD" if contract.contract_type == SALES else "CGDD"
    draft_id = f"seed-{contract.contract_no}-{idx}"
    session.add(Draft(id=draft_id, session_id="seed", user_id=user.id, dept_id=dept.id,
                      order_type=contract.contract_type, data={}, status="submitted", issues=[]))
    order = Order(
        order_no=f"{prefix}-{dept.code}-{day:%Y%m%d}-{idx:03d}", order_type=contract.contract_type, draft_id=draft_id,
        contract_id=contract.id, contract_no=contract.contract_no, dept_id=dept.id, party_name=party.name,
        project_name=project.name, address=project.address, contact=f"{project.contact} {project.phone}",
        operator_id=user.id, operator_name=user.display_name, dept_name=dept.name, biz_name="国内传统贸易",
        purchase_mode="直发", biz_tag="传统贸易", delivery_date=day + timedelta(days=3), total_amount=amount,
        total_qty=qty, over_quota=False, remark="历史订单", status=APPROVED, source="chat",
        submitted_at=datetime.combine(day, datetime.min.time()),
        items=[OrderItem(seq=1, material_code=code, material_name=material.name, spec=material.spec, quantity=qty,
                         unit=material.unit, unit_price=price, amount=amount)],
    )
    session.add(order)
    await session.flush()
    await trade_sync.sync_order(session, order)


async def ensure_database(url: str) -> None:
    u = make_url(url)
    server = create_async_engine(u.set(database=""))
    async with server.begin() as conn:
        await conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{u.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"))
    await server.dispose()


async def main() -> None:
    url = get_settings().database_url
    await ensure_database(url)
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await seed(session)
    await engine.dispose()
    print("初始化完成：", ", ".join(u[0] for u in USERS), f"（密码 {DEMO_PASSWORD}）")


if __name__ == "__main__":
    asyncio.run(main())
