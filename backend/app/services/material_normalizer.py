"""物料标准化：把俗称、简称、识别误差映射为物料字典中的标准编码（FR-016、C-002）。

顺序：别名或名称规格精确匹配 → rapidfuzz 在合同物料（无合同时为全字典）中召回候选
→ 候选得分明显领先时直接采用 → 候选并列且未写明规格时取合同首项物料（D-020）
→ 仍无法确定时由模型在候选中选择 → 都不行则留空并返回候选。
任何分支返回的编码都来自物料字典。
"""
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContractItem, Material, MaterialAlias

MIN_SCORE = 60
DECISIVE_SCORE = 85
DECISIVE_GAP = 8
TIE_GAP = 3

# 模型选择函数：给定原始描述和候选，返回候选中的编码或 None
Picker = Callable[[str, list[dict]], Awaitable[str | None]]


@dataclass
class Match:
    code: str | None
    method: str  # exact / fuzzy / contract_primary / llm / none
    candidates: list[dict] = field(default_factory=list)
    note: str = ""


def clean(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[\s\-_/]|φ|ф|mm|毫米", "", s)
    return s.replace("ф", "").replace("φ", "")


def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", s))


async def _alias_map(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(MaterialAlias.alias, MaterialAlias.material_code))).all()
    return {clean(a): c for a, c in rows}


def _texts(m: Material, aliases: list[str]) -> list[str]:
    return [m.name + m.spec, m.spec + m.name, m.spec, *aliases]


async def normalize(
    session: AsyncSession,
    raw_name: str,
    spec: str = "",
    contract_items: list[ContractItem] | None = None,
    picker: Picker | None = None,
) -> Match:
    raw_name, spec = (raw_name or "").strip(), (spec or "").strip()
    if not raw_name and not spec:
        return Match(None, "none")
    alias_map = await _alias_map(session)

    # 1. 精确匹配：编码、别名、名称+规格
    for key in (raw_name, raw_name + spec, spec + raw_name, spec):
        k = clean(key)
        if not k:
            continue
        code = alias_map.get(k)
        if code is None and await session.get(Material, key.strip().upper()) is not None:
            code = key.strip().upper()
        if code:
            # 精确命中即采用；不在合同范围内的由草稿校验提示，不改映射到其他物料
            return Match(code, "exact")

    # 2. 候选召回
    if contract_items:
        materials = [ci.material for ci in contract_items]
    else:
        materials = list((await session.execute(select(Material))).scalars().all())
    by_code: dict[str, list[str]] = {}
    for a, c in alias_map.items():
        by_code.setdefault(c, []).append(a)
    query = clean(raw_name + spec)
    q_nums = _numbers(query)
    scored = []
    for m in materials:
        score = max(fuzz.WRatio(query, clean(t)) for t in _texts(m, by_code.get(m.code, [])))
        m_nums = _numbers(clean(m.spec))
        if q_nums and m_nums:
            # 描述里写了规格数字时，数字对不上的候选降分
            score = score + 10 if q_nums & m_nums else score - 25
        scored.append((min(score, 100.0), m))
    scored.sort(key=lambda x: -x[0])
    cands = [
        {"code": m.code, "name": m.name, "spec": m.spec, "unit": m.unit, "score": round(s)}
        for s, m in scored[:5]
        if s >= MIN_SCORE
    ]
    if not cands:
        return Match(None, "none")

    top = cands[0]
    second = cands[1]["score"] if len(cands) > 1 else 0
    if top["score"] >= DECISIVE_SCORE and top["score"] - second >= DECISIVE_GAP:
        return Match(top["code"], "fuzzy", cands)

    # 3. 合同内候选并列、描述未写明规格时取合同首项物料（D-020）
    tied = {c["code"] for c in cands if top["score"] - c["score"] < TIE_GAP}
    tied_nums = [_numbers(clean(c["spec"])) for c in cands if c["code"] in tied]
    common = set.intersection(*tied_nums) if tied_nums else set()
    # 只有能区分并列候选的数字才算写明了规格（如 HRB400E 中的 400 不算）
    distinguishing = q_nums - common
    if contract_items and not distinguishing:
        for ci in contract_items:
            if ci.material_code in tied:
                return Match(
                    ci.material_code,
                    "contract_primary",
                    cands,
                    f"未写明规格，默认取合同首项物料 {ci.material.spec}，可在候选中切换",
                )

    # 4. 模型在候选中选择，返回值必须属于候选
    if picker is not None:
        picked = await picker(raw_name + (f" {spec}" if spec else ""), cands)
        if picked in {c["code"] for c in cands}:
            return Match(picked, "llm", cands)

    return Match(None, "none", cands)
