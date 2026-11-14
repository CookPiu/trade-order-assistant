"""物料标准化（FR-016、C-002、SC-002）。"""
from sqlalchemy import select

from app.models import Material, MaterialAlias
from app.services.draft_validator import find_contract
from app.services.material_normalizer import normalize


async def test_every_alias_maps_to_its_material(db):
    async with db() as s:
        rows = (await s.execute(select(MaterialAlias.alias, MaterialAlias.material_code))).all()
        codes = set((await s.execute(select(Material.code))).scalars().all())
        assert len(rows) >= len(codes)
        wrong = []
        for alias, code in rows:
            m = await normalize(s, alias)
            if m.code != code:
                wrong.append((alias, code, m.code))
        assert wrong == []


async def test_scenario_one_without_diameter_uses_contract_primary(db):
    async with db() as s:
        c = await find_contract(s, "2026-WZ-089")
        m = await normalize(s, "HRB400E 螺纹钢", "", c.items)
    assert m.code == "STL-RB-400E-20"
    assert m.method == "contract_primary"
    assert {x["code"] for x in m.candidates} >= {"STL-RB-400E-16", "STL-RB-400E-25"}


async def test_ocr_name_with_spec(db):
    async with db() as s:
        m = await normalize(s, "42.5水泥", "P.O42.5 散装")
    assert m.code == "CEM-PO-425"


async def test_fuzzy_variants(db):
    async with db() as s:
        c = await find_contract(s, "2026-WZ-089")
        assert (await normalize(s, "三级螺纹钢", "Φ25", c.items)).code == "STL-RB-400E-25"
        assert (await normalize(s, "罗纹钢16", "", c.items)).code == "STL-RB-400E-16"
        assert (await normalize(s, "普通硅酸盐水泥 42.5")).code == "CEM-PO-425"


async def test_unknown_material_returns_no_code(db):
    async with db() as s:
        m = await normalize(s, "不锈钢水槽")
        assert m.code is None
        # 模型若返回候选之外的编码也不采用
        async def bad_picker(_raw, _c):
            return "FAKE-001"

        m2 = await normalize(s, "钢材", "", None, bad_picker)
        assert m2.code != "FAKE-001"
