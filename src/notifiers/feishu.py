import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional

import requests


log = logging.getLogger(__name__)


class FeishuError(RuntimeError):
    """飞书推送异常。"""


def _gen_sign(secret: str) -> tuple[str, str]:
    """
    根据飞书自定义机器人签名规则生成 timestamp 和 sign。
    飞书规则（按官方文档描述）：
    1) 拼接签名字符串：timestamp + "\\n" + 密钥
    2) 使用 HmacSHA256 计算“空字符串”的签名结果
    3) 对签名结果进行 Base64 编码
    """
    timestamp = str(int(time.time()))
    key = f"{timestamp}\n{secret}".encode("utf-8")
    hmac_code = hmac.new(key, msg=b"", digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(hmac_code).decode("utf-8")
    return timestamp, sign


def _build_text_payload(
    text: str,
    *,
    secret: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "msg_type": "text",
        "content": {
            "text": text,
        },
    }

    if secret:
        timestamp, sign = _gen_sign(secret)
        payload["timestamp"] = timestamp
        payload["sign"] = sign

    return payload


def _raise_if_feishu_error(resp: requests.Response) -> None:
    if resp.status_code >= 400:
        raise FeishuError(f"HTTP {resp.status_code} {resp.reason}: {resp.text[:500]}")

    try:
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        raise FeishuError(f"飞书返回的不是合法 JSON：{resp.text[:500]}") from e

    # 飞书 webhook 常见成功格式：
    # {"StatusCode":0,"StatusMessage":"success"}
    # 或 {"code":0,"msg":"success"}
    code = data.get("code", data.get("StatusCode", 0))
    if str(code) not in {"0", "None"} and code != 0:
        raise FeishuError(f"飞书返回失败：{json.dumps(data, ensure_ascii=False)}")


def send_text(
    webhook_url: str,
    text: str,
    *,
    secret: Optional[str] = None,
    timeout_s: float = 15.0,
) -> None:
    """
    第一版：发送最稳的 text 消息。
    如果配置了 secret，则自动附带 timestamp/sign。
    """
    if not webhook_url:
        raise FeishuError("缺少 FEISHU_WEBHOOK_URL")

    if not text.strip():
        raise FeishuError("发送内容为空")

    payload = _build_text_payload(text=text, secret=secret)

    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=timeout_s,
        )
        _raise_if_feishu_error(resp)
        log.info("飞书推送成功")
    except requests.Timeout as e:
        raise FeishuError(f"飞书推送超时：{e!r}") from e
    except requests.RequestException as e:
        raise FeishuError(f"飞书请求异常：{e!r}") from e
    except Exception as e:  # noqa: BLE001
        raise FeishuError(f"飞书推送失败：{e!r}") from e


def markdown_to_text(title: str, markdown_text: str) -> str:
    """
    第一版偷懒做法：把 Markdown 日报包装成纯文本发出去。
    后续如果你真的要富文本/卡片，再单独扩展。
    """
    title = (title or "").strip()
    body = (markdown_text or "").strip()

    if title and body:
        return f"{title}\n\n{body}"
    if title:
        return title
    return body


def send_daily_report(
    webhook_url: str,
    title: str,
    markdown_text: str,
    *,
    secret: Optional[str] = None,
    timeout_s: float = 15.0,
) -> None:
    """
    给 main.py 调用的统一入口。
    先把 Markdown 转成纯文本，再发送。
    """
    text = markdown_to_text(title=title, markdown_text=markdown_text)
    send_text(
        webhook_url=webhook_url,
        text=text,
        secret=secret,
        timeout_s=timeout_s,
    )