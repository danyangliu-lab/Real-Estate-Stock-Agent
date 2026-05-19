"""
腾讯云 TokenHub 多模型客户端（MiniMax M2.7 + DeepSeek V4 Pro + Kimi K2.6 三模型）
- 三个模型均通过腾讯云 TokenHub OpenAI 兼容接口调用（Bearer Token）
- 文档：https://cloud.tencent.com/document/product/1823/130078
"""

import logging
from typing import Optional

import httpx

from app.config import (
    MINIMAX_MODEL, MINIMAX_ENABLED,
    GLM_MODEL, GLM_ENABLED,
    KIMI_MODEL, KIMI_ENABLED,
    TOKENHUB_API_KEY, TOKENHUB_BASE_URL,
)

logger = logging.getLogger(__name__)


# ========== TokenHub OpenAI 兼容接口通用调用 ==========

async def _call_tokenhub_openai(
    model: str,
    prompt: str,
    system: str = "",
    temperature: Optional[float] = None,
    enable_search: bool = False,  # 兼容旧调用，TokenHub 上当前三模型均不支持 ai_search，统一忽略
    label: str = "",
) -> Optional[str]:
    """调用腾讯云 TokenHub OpenAI 兼容接口（三模型共用）"""
    if not TOKENHUB_API_KEY:
        logger.warning(f"未配置 TOKENHUB_API_KEY，跳过 {label} 调用")
        return None

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        body["temperature"] = temperature
    # 注：腾讯云 TokenHub 上的 minimax-m2.7 / deepseek-v4-pro / kimi-k2.6
    # 均不支持 enable_search/ai_search 字段（会返回 400 gateway_error code=400005），
    # 故此处不再把 enable_search 透传到接口；联网检索改由上游 prompt 自行注入背景信息。
    _ = enable_search  # 显式标记保留参数

    headers = {
        "Authorization": f"Bearer {TOKENHUB_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{TOKENHUB_BASE_URL}/chat/completions",
                headers=headers,
                json=body,
            )
            if resp.status_code >= 400:
                # 把网关返回的 error 信息打出来，便于排查
                logger.error(f"{label} HTTP {resp.status_code}: {resp.text[:500]}")
                return None
            data = resp.json()

            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0].get("message", {})
                content = msg.get("content", "") or ""
                # TokenHub 上部分模型（含推理过程）会先返回 reasoning_content，
                # 真正答案在 content 中；若 content 为空则回退到 reasoning_content。
                if not content:
                    content = msg.get("reasoning_content", "") or ""
                return content if content else None
            elif "error" in data:
                err = data["error"]
                logger.error(f"{label} API错误: {err}")
                return None
            else:
                logger.error(f"{label} API响应异常: {data}")
                return None
    except Exception as e:
        logger.error(f"调用{label} API失败: {e}")
        return None


# 兼容旧名（其他模块若 import 过 _call_lkeap_openai，仍可用）
_call_lkeap_openai = _call_tokenhub_openai


# ── MiniMax M2.7 ──

async def chat_minimax(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    enable_search: bool = False,
) -> Optional[str]:
    """调用 MiniMax M2.7（腾讯云 TokenHub）"""
    if not MINIMAX_ENABLED:
        return None
    return await _call_tokenhub_openai(
        model=MINIMAX_MODEL,
        prompt=prompt,
        system=system,
        temperature=temperature,
        enable_search=enable_search,
        label="MiniMax-M2.7",
    )


async def chat_deepseek(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    enable_search: bool = False,
) -> Optional[str]:
    """chat_minimax 的兼容别名"""
    return await chat_minimax(prompt, system, temperature, enable_search)


async def chat_hunyuan(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    enable_search: bool = False,
) -> Optional[str]:
    """chat_minimax 的别名，兼容旧版调用"""
    return await chat_minimax(prompt, system, temperature, enable_search)


# ── DeepSeek V4 Pro（保留 chat_glm 函数名以兼容已有调用）──

async def chat_glm(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
) -> Optional[str]:
    """调用 DeepSeek V4 Pro（腾讯云 TokenHub）

    注意：函数名保留为 chat_glm 以兼容已有调用方，实际模型已切换为 DeepSeek V4 Pro
    """
    if not GLM_ENABLED:
        return None
    return await _call_tokenhub_openai(
        model=GLM_MODEL,
        prompt=prompt,
        system=system,
        temperature=temperature,
        label="DeepSeek-V4-Pro",
    )


# ── Kimi K2.6 ──

async def chat_kimi(
    prompt: str,
    system: str = "",
) -> Optional[str]:
    """调用 Kimi K2.6（腾讯云 TokenHub）
    注意：Kimi 系列暂不支持 temperature / top_p 参数
    """
    if not KIMI_ENABLED:
        return None
    return await _call_tokenhub_openai(
        model=KIMI_MODEL,
        prompt=prompt,
        system=system,
        temperature=None,  # Kimi 系列不支持
        label="Kimi-K2.6",
    )
