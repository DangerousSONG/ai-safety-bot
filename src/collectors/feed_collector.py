import logging
import re
import calendar
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
                # 用 timegm 按 UTC 解释，避免本地时区导致的偏差
                ts = calendar.timegm(v)
                return datetime.fromtimestamp(ts)
            except Exception:  # noqa: BLE001
                return None
    return None


_TAG_RE = re.compile(r"<[^>]+>")


def _extract_summary(entry: Dict[str, Any]) -> str:
    """
    从 RSS/Atom entry 中尽量取到 summary/description 的纯文本。
    第一版：只做轻量清洗（去标签、压缩空白）。
    """
    candidates: List[str] = []
    for k in ("summary", "description", "subtitle"):
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            candidates.append(v)

    # 某些 feed 会放在 content 列表里
    content = entry.get("content")
    if isinstance(content, list) and content:
        for c in content:
            if isinstance(c, dict):
                v = c.get("value")
                if isinstance(v, str) and v.strip():
                    candidates.append(v)
                    break

    if not candidates:
        return ""

    raw = candidates[0]
    text = _TAG_RE.sub(" ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_feed_entries(
    source: Dict[str, Any],
    *,
    max_entries: int = 30,
    timeout_s: float = 15.0,
    recent_days: int = 30,
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

            published_at = _to_datetime(e)
            if published_at:
                # 最近 N 天过滤（以本机当前时间为基准；Actions 环境为 UTC，不影响“30天窗口”的相对判断）
                age_days = (datetime.utcnow() - published_at).days
                if age_days > recent_days:
                    continue

            summary = _extract_summary(e)
            entries.append(
                {
                    "title": title,
                    "url": link,
                    "published_at": published_at,
                    "summary": summary,
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

