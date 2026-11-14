"""文本模型（DeepSeek）与视觉模型（百炼）客户端，均走 OpenAI 兼容接口。

调用失败统一抛出 LLMError，由上层转换为对话流中的失败提示（边界情况·模型失败）。
"""
import base64
import json
import logging
import re
from typing import Any

from openai import APIError, APITimeoutError, AsyncOpenAI, DefaultAsyncHttpxClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services import params

log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


_clients: dict[str, AsyncOpenAI] = {}


def _client(kind: str) -> AsyncOpenAI:
    s = get_settings()
    if kind not in _clients:
        # DeepSeek 与百炼都是国内服务，默认不走系统代理，避免本地代理转发导致超时
        http_client = DefaultAsyncHttpxClient(trust_env=s.llm_use_system_proxy)
        if kind == "text":
            if not s.deepseek_api_key:
                raise LLMError("未配置 DEEPSEEK_API_KEY")
            _clients[kind] = AsyncOpenAI(
                api_key=s.deepseek_api_key, base_url=s.deepseek_base_url, max_retries=1, http_client=http_client
            )
        else:
            if not s.dashscope_api_key:
                raise LLMError("未配置 DASHSCOPE_API_KEY")
            _clients[kind] = AsyncOpenAI(
                api_key=s.dashscope_api_key, base_url=s.dashscope_base_url, max_retries=1, http_client=http_client
            )
    return _clients[kind]


def parse_json(content: str) -> dict[str, Any]:
    """从模型输出中取出 JSON 对象，兼容 ```json 代码块包裹。"""
    text = content.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            raise LLMError("模型输出不是 JSON")
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"模型输出 JSON 解析失败：{e}") from e
    if not isinstance(data, dict):
        raise LLMError("模型输出不是 JSON 对象")
    return data


async def chat_json(session: AsyncSession, system: str, user: str) -> dict[str, Any]:
    cfg = await params.get_param(session, "llm")
    s = get_settings()
    try:
        resp = await _client("text").chat.completions.create(
            model=cfg.get("model") or s.deepseek_model,
            temperature=float(cfg.get("temperature", 0.1)),
            timeout=float(cfg.get("timeout") or s.llm_timeout_seconds),
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            # 抽取任务不需要推理过程，关闭思考可把单轮耗时从约 3 秒降到约 1.5 秒（本机实测）
            extra_body=None if cfg.get("thinking") else {"thinking": {"type": "disabled"}},
        )
    except (APIError, APITimeoutError) as e:
        log.warning("text model call failed: %s", e)
        raise LLMError(f"文本模型调用失败：{type(e).__name__}") from e
    return parse_json(resp.choices[0].message.content or "")


async def vision_json(session: AsyncSession, prompt: str, image: bytes, mime: str) -> dict[str, Any]:
    cfg = await params.get_param(session, "vision")
    s = get_settings()
    url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    try:
        resp = await _client("vision").chat.completions.create(
            model=cfg.get("model") or s.vision_model,
            temperature=float(cfg.get("temperature", 0.1)),
            timeout=float(cfg.get("timeout") or 60),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    except (APIError, APITimeoutError) as e:
        log.warning("vision model call failed: %s", e)
        raise LLMError(f"视觉模型调用失败：{type(e).__name__}") from e
    return parse_json(resp.choices[0].message.content or "")
