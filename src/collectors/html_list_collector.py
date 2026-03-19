import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.utils.http import HttpError, http_get_text


log = logging.getLogger(__name__)


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_META_DESC_RE = re.compile(
    r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# 粗略日期匹配：2026-03-18 / 2026/03/18 / 2026.03.18
_DATE_RE = re.compile(r"(?P<y>20\d{2})[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})")

# href 提取（尽量简单）
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


def _strip_html(s: str) -> str:
    t = _TAG_RE.sub(" ", s or "")
    t = _SPACE_RE.sub(" ", t).strip()
    return t


def _extract_title(html: str) -> str:
    m = _TITLE_RE.search(html or "")
    if not m:
        return ""
    return _strip_html(m.group(1))


def _extract_meta_description(html: str) -> str:
    m = _META_DESC_RE.search(html or "")
    if not m:
        return ""
    return _strip_html(m.group(1))


def _find_first_date_near(html: str, idx: int, *, window: int = 500) -> Optional[datetime]:
    """
    从某个位置附近窗口中找一个日期，并转成 UTC 的 datetime（仅日期）。
    """
    if not html:
        return None
    start = max(0, idx - window)
    end = min(len(html), idx + window)
    chunk = html[start:end]
    m = _DATE_RE.search(chunk)
    if not m:
        return None
    try:
        y = int(m.group("y"))
        mo = int(m.group("m"))
        d = int(m.group("d"))
        return datetime(y, mo, d, tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _dedupe_by_url(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        u = str(it.get("url") or "")
        if not u:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out


def fetch_html_list_entries(
    source: Dict[str, Any],
    *,
    max_entries: int = 30,
    timeout_s: float = 15.0,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    第一版 html_list：只抓取“固定白名单页面”。
    - 对于“列表类页面”（如 ModelScope Learn）：尽力从页面里提取多条链接与日期
    - 对于“单页”（如产品页/新闻稿）：至少生成 1 条条目（title + url + meta description）
    解析失败时返回错误字符串，不抛异常。
    """
    name = source.get("name", "(unknown)")
    url = source.get("url")
    if not url:
        return [], f"源缺少 url：{name}"

    try:
        html = http_get_text(str(url), timeout_s=timeout_s)
        title = _extract_title(html)
        desc = _extract_meta_description(html)

        items: List[Dict[str, Any]] = []

        # 特化：ModelScope Learn 尝试提取多条 /learn/ 相关文章链接
        if "modelscope" in str(url).lower() and "/learn" in str(url).lower():
            hrefs = list(_HREF_RE.finditer(html))
            for m in hrefs:
                href = (m.group(1) or "").strip()
                if not href or href.startswith("#"):
                    continue
                abs_url = urljoin(str(url), href)
                if "/learn" not in abs_url:
                    continue
                if abs_url.rstrip("/") == str(url).rstrip("/"):
                    continue

                published_at = _find_first_date_near(html, m.start())
                items.append(
                    {
                        "title": "",  # 先留空：第一版不做复杂 DOM 解析，title 可回退为页面 title
                        "url": abs_url,
                        "published_at": published_at,
                        "summary": "",
                        "source_name": name,
                        "category": source.get("category", ""),
                        "content_trust": source.get("content_trust", ""),
                        "delivery_trust": source.get("delivery_trust", ""),
                    }
                )

            items = _dedupe_by_url(items)[:max_entries]

            # 对于 title 为空的条目，用页面 title 兜底（保持“够用”）
            for it in items:
                if not (it.get("title") or "").strip():
                    it["title"] = title or "ModelScope Learn"

            if items:
                log.info("抓取成功（html_list）：source=%s entries=%d", name, len(items))
                return items, None

        # 默认：单页兜底
        if not title:
            title = name
        items.append(
            {
                "title": title,
                "url": str(url),
                "published_at": _find_first_date_near(html, 0),
                "summary": desc,
                "source_name": name,
                "category": source.get("category", ""),
                "content_trust": source.get("content_trust", ""),
                "delivery_trust": source.get("delivery_trust", ""),
            }
        )

        log.info("抓取成功（html_list）：source=%s entries=%d", name, len(items))
        return items, None
    except HttpError as e:
        msg = f"抓取失败（HTTP）：source={name} url={url} err={e}"
        log.error(msg)
        return [], msg
    except Exception as e:  # noqa: BLE001
        msg = f"抓取失败（未知错误）：source={name} url={url} err={repr(e)}"
        log.exception(msg)
        return [], msg

