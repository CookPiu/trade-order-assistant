"""系统参数配置（FR-051、US6）：公允价偏离比例、履约配额阈值、固定业务属性、大模型调用参数，仅系统管理员可用。

参数保存在 system_param 表，读取时与默认值合并（app/services/params.py），修改后下一次请求即生效。
"""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import BizError
from app.core.security import require_roles
from app.models import ROLE_ADMIN, SystemParam, User
from app.services import audit
from app.services.params import DEFAULTS, DESCRIPTIONS, get_param

router = APIRouter(prefix="/api/params", tags=["params"])
admin = require_roles(ROLE_ADMIN)


class FixedAttrs(BaseModel):
    biz_name: str = Field(min_length=1, max_length=32)
    purchase_mode: str = Field(min_length=1, max_length=16)
    biz_tag: str = Field(min_length=1, max_length=16)


class Deviation(BaseModel):
    value: float = Field(gt=0, le=1)


class WarnRatio(BaseModel):
    value: float = Field(ge=0, lt=1)


class LlmParams(BaseModel):
    model: str = Field("", max_length=64)
    temperature: float = Field(ge=0, le=2)
    timeout: int = Field(ge=5, le=300)
    thinking: bool = False


class VisionParams(BaseModel):
    model: str = Field("", max_length=64)
    temperature: float = Field(ge=0, le=2)
    timeout: int = Field(ge=5, le=300)


SCHEMAS: dict[str, type[BaseModel]] = {
    "fixed_attrs": FixedAttrs,
    "fair_price_deviation": Deviation,
    "quota_warn_ratio": WarnRatio,
    "llm": LlmParams,
    "vision": VisionParams,
}
SCALAR = {"fair_price_deviation", "quota_warn_ratio"}

FIELD_LABEL = {
    "biz_name": "业务名称", "purchase_mode": "采购模式", "biz_tag": "业务标签", "value": "取值",
    "model": "模型名", "temperature": "温度", "timeout": "超时（秒）", "thinking": "思考模式",
}


class ParamView(BaseModel):
    key: str
    value: Any
    default: Any
    description: str


class ParamUpdate(BaseModel):
    value: Any


def _validate(key: str, value: Any) -> Any:
    schema = SCHEMAS[key]
    try:
        if key in SCALAR:
            return schema(value=value).value
        if not isinstance(value, dict):
            raise BizError(422, "参数格式不正确")
        return schema(**value).model_dump()
    except ValidationError as e:
        err = e.errors()[0]
        field = FIELD_LABEL.get(str(err["loc"][0]) if err["loc"] else "", "")
        raise BizError(422, f"{field}：{err['msg']}" if field else err["msg"])


async def _view(session: AsyncSession, key: str) -> ParamView:
    return ParamView(key=key, value=await get_param(session, key), default=DEFAULTS[key], description=DESCRIPTIONS[key])


@router.get("", response_model=list[ParamView])
async def list_params(_: User = Depends(admin), session: AsyncSession = Depends(get_session)):
    return [await _view(session, k) for k in DEFAULTS]


@router.put("/{key}", response_model=ParamView)
async def update_param(
    key: str, body: ParamUpdate, user: User = Depends(admin), session: AsyncSession = Depends(get_session)
):
    if key not in SCHEMAS:
        raise BizError(404, "参数不存在")
    value = _validate(key, body.value)
    before = await get_param(session, key)
    row = await session.get(SystemParam, key)
    if row is None:
        session.add(SystemParam(key=key, value=value, description=DESCRIPTIONS[key]))
    else:
        row.value = value
    audit.record(session, user, audit.PARAM_UPDATE, detail={"key": key, "before": before, "after": value})
    await session.commit()
    return await _view(session, key)
