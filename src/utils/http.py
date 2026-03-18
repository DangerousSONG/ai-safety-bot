import logging
import time
from typing import Optional

import requests


log = logging.getLogger(__name__)


DEFAULT_USER_AGENT = "ai-safety-daily-bot/0.1 (+https://github.com/)"


class HttpError(RuntimeError):
    pass


def http_get_text(
    url: str,
    *,
    timeout_s: float = 15.0,
    max_retries: int = 2,
    backoff_s: float = 0.8,
    user_agent: str = DEFAULT_USER_AGENT,
) -> str:
    """
    最小可用的 GET 请求封装：
    - 超时
    - 少量重试（网络抖动/临时 5xx）
    - 错误信息明确
    """
    headers = {"User-Agent": user_agent}
    last_err: Optional[BaseException] = None

    for attempt in range(1, max_retries + 2):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout_s)
            if resp.status_code >= 400:
                raise HttpError(f"HTTP {resp.status_code} {resp.reason}")
            resp.encoding = resp.encoding or "utf-8"
            return resp.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt <= max_retries:
                sleep_s = backoff_s * (2 ** (attempt - 1))
                log.warning("GET 失败，将重试：url=%s attempt=%s/%s err=%s; %.1fs 后重试", url, attempt, max_retries + 1, repr(e), sleep_s)
                time.sleep(sleep_s)
                continue
            break

    raise HttpError(f"GET 最终失败：url={url} err={repr(last_err)}")

