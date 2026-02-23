"""
腾讯混元大模型客户端
使用 HTTPS API 直接调用，通过 TC3-HMAC-SHA256 签名认证
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import HUNYUAN_SECRET_ID, HUNYUAN_SECRET_KEY, HUNYUAN_MODEL

logger = logging.getLogger(__name__)

HUNYUAN_ENDPOINT = "hunyuan.tencentcloudapi.com"
SERVICE = "hunyuan"
VERSION = "2023-09-01"
ACTION = "ChatCompletions"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _build_tc3_auth(timestamp: int, payload: str) -> str:
    """构建 TC3-HMAC-SHA256 签名"""
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")

    # 1. 拼接规范请求串
    http_request_method = "POST"
    canonical_uri = "/"
    canonical_querystring = ""
    canonical_headers = (
        f"content-type:application/json; charset=utf-8\n"
        f"host:{HUNYUAN_ENDPOINT}\n"
        f"x-tc-action:{ACTION.lower()}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = _sha256(payload.encode("utf-8"))
    canonical_request = (
        f"{http_request_method}\n{canonical_uri}\n{canonical_querystring}\n"
        f"{canonical_headers}\n{signed_headers}\n{hashed_payload}"
    )

    # 2. 拼接待签名字符串
    algorithm = "TC3-HMAC-SHA256"
    credential_scope = f"{date}/{SERVICE}/tc3_request"
    hashed_canonical_request = _sha256(canonical_request.encode("utf-8"))
    string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"

    # 3. 计算签名
    secret_date = _hmac_sha256(f"TC3{HUNYUAN_SECRET_KEY}".encode("utf-8"), date.encode("utf-8"))
    secret_service = _hmac_sha256(secret_date, SERVICE.encode("utf-8"))
    secret_signing = _hmac_sha256(secret_service, b"tc3_request")
    signature = _hmac_sha256(secret_signing, string_to_sign.encode("utf-8")).hex()

    # 4. 拼接 Authorization
    authorization = (
        f"{algorithm} Credential={HUNYUAN_SECRET_ID}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return authorization


async def chat_hunyuan(prompt: str, system: str = "", temperature: float = 0.3) -> Optional[str]:
    """调用腾讯混元大模型"""
    if not HUNYUAN_SECRET_ID or not HUNYUAN_SECRET_KEY:
        logger.warning("未配置腾讯混元 API 密钥，跳过 AI 评级")
        return None

    messages = []
    if system:
        messages.append({"Role": "system", "Content": system})
    messages.append({"Role": "user", "Content": prompt})

    payload = json.dumps({
        "Model": HUNYUAN_MODEL,
        "Messages": messages,
        "Temperature": temperature,
        "TopP": 0.8,
        "Stream": False,
        "EnableEnhancement": False,
    })

    timestamp = int(time.time())
    authorization = _build_tc3_auth(timestamp, payload)

    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": HUNYUAN_ENDPOINT,
        "X-TC-Action": ACTION,
        "X-TC-Version": VERSION,
        "X-TC-Timestamp": str(timestamp),
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"https://{HUNYUAN_ENDPOINT}",
                headers=headers,
                content=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            if "Response" in data and "Choices" in data["Response"]:
                return data["Response"]["Choices"][0]["Message"]["Content"]
            elif "Response" in data and "Error" in data["Response"]:
                err = data["Response"]["Error"]
                logger.error(f"混元API错误: [{err.get('Code')}] {err.get('Message')}")
                return None
            else:
                logger.error(f"混元API响应异常: {data}")
                return None
    except Exception as e:
        logger.error(f"调用混元API失败: {e}")
        return None
