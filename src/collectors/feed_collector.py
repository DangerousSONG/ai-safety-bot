import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import feedparser

from src.utils.http import HttpError, http_get_text


log = logging.getLogger(__name__)


def _to_datetime(entry: Dict[str, Any]) -> Optional[datetime]:
    # feedparser 会提供 published_parsed / updated_parsed（time.struct_time）
    for key in ("published_parsed", "updated_parsed"):
        v = entry.get(key)
        if v:
            try:
                return datetime(*v[:6])
            except Exception:  # noqa: BLE001
                return None
    return None


def fetch_feed_entries(
    source: Dict[str, Any],
    *,
    max_entries: int = 30,
    timeout_s: float = 15.0,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    抓取单个 RSS/Atom 源，返回 (entries, error_message)。
    失败时不抛出，保证上层流程不中断。
    """
    name = source.get("name", "(unknown)")
    url = source.get("url")
    if not url:
        return [], f"源缺少 url：{name}"

    try:
        text = http_get_text(url, timeout_s=timeout_s)
        parsed = feedparser.parse(text)

        if parsed.get("bozo"):
            bozo_exc = parsed.get("bozo_exception")
            log.warning("Feed 解析 bozo：source=%s url=%s err=%s", name, url, repr(bozo_exc))

        raw_entries = parsed.get("entries") or []
        entries: List[Dict[str, Any]] = []
        for e in raw_entries[:max_entries]:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue
            entries.append(
                {
                    "title": title,
                    "url": link,
                    "published_at": _to_datetime(e),
                    "source_name": name,
                    "category": source.get("category", ""),
                    "content_trust": source.get("content_trust", ""),
                    "delivery_trust": source.get("delivery_trust", ""),
                }
            )

        log.info("抓取成功：source=%s entries=%d (raw=%d)", name, len(entries), len(raw_entries))
        return entries, None
    except HttpError as e:
        msg = f"抓取失败（HTTP）：source={name} url={url} err={e}"
        log.error(msg)
        return [], msg
    except Exception as e:  # noqa: BLE001
        msg = f"抓取失败（未知错误）：source={name} url={url} err={repr(e)}"
        log.exception(msg)
        return [], msg

