import logging
import json
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
_META_PROP_RE = re.compile(
    r'<meta\s+[^>]*property=["\']([^"\']+)["\'][^>]*content=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
_META_NAME_RE = re.compile(
    r'<meta\s+[^>]*name=["\']([^"\']+)["\'][^>]*content=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)

# 粗略日期匹配：2026-03-18 / 2026/03/18 / 2026.03.18
_DATE_RE = re.compile(r"(?P<y>20\d{2})[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})")

# href 提取（尽量简单）
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

# <a ... href="...">anchor text</a>
_A_HREF_TEXT_RE = re.compile(
    r'<a\b[^>]*href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<text>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


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


def _extract_meta(html: str) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    for m in _META_PROP_RE.finditer(html or ""):
        k = (m.group(1) or "").strip().lower()
        v = _strip_html(m.group(2) or "")
        if k and v and k not in meta:
            meta[k] = v
    for m in _META_NAME_RE.finditer(html or ""):
        k = (m.group(1) or "").strip().lower()
        v = _strip_html(m.group(2) or "")
        if k and v and k not in meta:
            meta[k] = v
    return meta


def _parse_jsonld_objects(html: str) -> List[Dict[str, Any]]:
    objs: List[Dict[str, Any]] = []
    for m in _JSONLD_RE.finditer(html or ""):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        if isinstance(data, dict):
            objs.append(data)
        elif isinstance(data, list):
            for x in data:
                if isinstance(x, dict):
                    objs.append(x)
    return objs


def _jsonld_find_best(objs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    从 JSON-LD 里挑一个最像 Article/NewsArticle/WebPage 的对象。
    """
    best: Dict[str, Any] = {}
    for o in objs:
        t = str(o.get("@type") or "")
        t_l = t.lower()
        if any(k in t_l for k in ("newsarticle", "article", "report", "webpage")):
            best = o
            break
    return best


def _parse_dt_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    ss = s.strip()
    try:
        # 兼容 Z
        if ss.endswith("Z"):
            ss = ss[:-1] + "+00:00"
        dt = datetime.fromisoformat(ss)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _extract_published_at(html: str) -> Optional[datetime]:
    meta = _extract_meta(html)
    # 常见 meta 时间字段
    for k in (
        "article:published_time",
        "og:updated_time",
        "published_time",
        "pubdate",
        "date",
    ):
        if k in meta:
            dt = _parse_dt_iso(meta[k])
            if dt:
                return dt

    # JSON-LD datePublished / dateCreated
    objs = _parse_jsonld_objects(html)
    o = _jsonld_find_best(objs)
    for k in ("datePublished", "dateCreated", "dateModified"):
        v = o.get(k) if isinstance(o, dict) else None
        if isinstance(v, str):
            dt = _parse_dt_iso(v)
            if dt:
                return dt

    # 最后兜底：全文找一个日期
    return _find_first_date_near(html, 0)


def _extract_best_title(html: str, *, fallback: str) -> str:
    meta = _extract_meta(html)
    for k in ("og:title", "twitter:title"):
        if k in meta and meta[k].strip():
            return meta[k].strip()
    # JSON-LD headline/name
    o = _jsonld_find_best(_parse_jsonld_objects(html))
    for k in ("headline", "name"):
        v = o.get(k) if isinstance(o, dict) else None
        if isinstance(v, str) and v.strip():
            return v.strip()
    t = _extract_title(html)
    return t or fallback


def _extract_best_summary(html: str) -> str:
    meta = _extract_meta(html)
    for k in ("og:description", "twitter:description", "description"):
        if k in meta and meta[k].strip():
            return meta[k].strip()
    # JSON-LD description
    o = _jsonld_find_best(_parse_jsonld_objects(html))
    v = o.get("description") if isinstance(o, dict) else None
    if isinstance(v, str) and v.strip():
        return _strip_html(v)
    return _extract_meta_description(html)


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
        title = _extract_best_title(html, fallback=name)
        desc = _extract_best_summary(html)
        published_at_page = _extract_published_at(html)

        items: List[Dict[str, Any]] = []

        url_l = str(url).lower()
        name_l = str(name).lower()

        # ---------------------------
        # ModelScope Learn：尽量抓多条，且提取每条真实标题
        # ---------------------------
        if "modelscope" in url_l and "/learn" in url_l:
            for m in _A_HREF_TEXT_RE.finditer(html):
                href = (m.group("href") or "").strip()
                if not href or href.startswith("#"):
                    continue
                abs_url = urljoin(str(url), href)
                if "/learn" not in abs_url:
                    continue
                if abs_url.rstrip("/") == str(url).rstrip("/"):
                    continue

                anchor_text = _strip_html(m.group("text") or "")
                # 过滤掉过短/明显不是标题的锚文本
                if len(anchor_text) < 6:
                    continue
                if anchor_text.lower() in {"learn", "more", "read more", "详情"}:
                    continue

                published_at = _find_first_date_near(html, m.start())
                # 尝试在链接附近抓一个简短摘要（就近窗口去标签）
                near = html[max(0, m.start() - 300) : min(len(html), m.end() + 600)]
                near_text = _strip_html(near)
                # 去掉标题本身，避免重复
                near_text = near_text.replace(anchor_text, "").strip()
                summary = near_text[:220].strip() if near_text else ""

                items.append(
                    {
                        "title": anchor_text,
                        "url": abs_url,
                        "published_at": published_at,
                        "summary": summary,
                        "source_name": name,
                        "category": source.get("category", ""),
                        "content_trust": source.get("content_trust", ""),
                        "delivery_trust": source.get("delivery_trust", ""),
                    }
                )

            items = _dedupe_by_url(items)[:max_entries]
            if items:
                log.info("抓取成功（html_list）：source=%s entries=%d", name, len(items))
                return items, None

        # ---------------------------
        # Volcengine LLMScan：页面多为单页，但尽量提取更好的 title/summary/date
        # ---------------------------
        if "volcengine" in url_l or "llmscan" in name_l:
            items.append(
                {
                    "title": title or name,
                    "url": str(url),
                    "published_at": published_at_page,
                    "summary": desc,
                    "source_name": name,
                    "category": source.get("category", ""),
                    "content_trust": source.get("content_trust", ""),
                    "delivery_trust": source.get("delivery_trust", ""),
                }
            )
            log.info("抓取成功（html_list）：source=%s entries=%d", name, len(items))
            return items, None

        # ---------------------------
        # Ant Group AI Safety News：新闻稿单页，尽量用 meta/JSON-LD 提取
        # ---------------------------
        if "antgroup" in url_l or "ant group" in name_l:
            items.append(
                {
                    "title": title or name,
                    "url": str(url),
                    "published_at": published_at_page,
                    "summary": desc,
                    "source_name": name,
                    "category": source.get("category", ""),
                    "content_trust": source.get("content_trust", ""),
                    "delivery_trust": source.get("delivery_trust", ""),
                }
            )
            log.info("抓取成功（html_list）：source=%s entries=%d", name, len(items))
            return items, None

        # 默认：单页兜底
        items.append(
            {
                "title": title or name,
                "url": str(url),
                "published_at": published_at_page,
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

