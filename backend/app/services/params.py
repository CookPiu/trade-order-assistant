"""系统参数读取，未配置时使用默认值。"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemParam

DEFAULTS: dict[str, Any] = {
    "fixed_attrs": {"biz_name": "国内传统贸易", "purchase_mode": "直发", "biz_tag": "传统贸易"},
    # 单价偏离公允价超过该比例时提醒
    "fair_price_deviation": 0.1,
    # 提交后剩余金额占合同总金额低于该比例时提醒
    "quota_warn_ratio": 0.1,
    "llm": {"model": "", "temperature": 0.1, "timeout": 30, "thinking": False},
    "vision": {"model": "", "temperature": 0.1, "timeout": 60},
}

DESCRIPTIONS = {
    "fixed_attrs": "固定业务属性：业务名称、采购模式、业务标签",
    "fair_price_deviation": "单价偏离公允价的允许比例（0.1 表示 10%）",
    "quota_warn_ratio": "履约配额阈值：提交后剩余金额占合同总金额低于该比例时提醒",
    "llm": "文本模型参数，model 为空时使用 .env 中的 DEEPSEEK_MODEL；thinking 为 true 时开启思考模式",
    "vision": "视觉模型参数，model 为空时使用 .env 中的 VISION_MODEL",
}


async def get_param(session: AsyncSession, key: str) -> Any:
    row = await session.get(SystemParam, key)
    if row is None:
        return DEFAULTS[key]
    default = DEFAULTS.get(key)
    if isinstance(default, dict) and isinstance(row.value, dict):
        return {**default, **row.value}
    return row.value
