import json
import logging
from typing import Any, Dict

import requests


log = logging.getLogger(__name__)


class FeishuError(RuntimeError):
    pass


def send_markdown(webhook_url: str, title: str, markdown_text: str, *, timeout_s: float = 15.0) -> None:
    """
    第一版：用飞书 bot webhook 发送“post”消息（支持 Markdown）。
    """
    if not webhook_url:
        raise FeishuError("缺少 FEISHU_WEBHOOK_URL")

    payload: Dict[str, Any] = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": [
                        [
                            {
                                "tag": "md",
                                "text": markdown_text,
                            }
                        ]
                    ],
                }
            }
        },
    }

    try:
        resp = requests.post(
            webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=timeout_s,
        )
        if resp.status_code >= 400:
            raise FeishuError(f"HTTP {resp.status_code} {resp.reason}: {resp.text[:300]}")

        # 飞书 webhook 通常返回 {"StatusCode":0,...} 或 {"code":0,...}
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = None

        if isinstance(data, dict):
            code = data.get("code", data.get("StatusCode", 0))
            if code not in (0, "0", None):
                raise FeishuError(f"飞书返回非0：{data}")

        log.info("飞书推送成功")
    except Exception as e:  # noqa: BLE001
        raise FeishuError(f"飞书推送失败：{repr(e)}") from e

