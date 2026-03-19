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


def _is_modelscope_learn_article_url(u: str) -> bool:
    """
    尽量过滤掉导航/栏目/分页/搜索等噪音链接，只保留更像“文章详情”的链接。
    """
    ul = (u or "").strip().lower()
    if not ul:
        return False
    if "modelscope.cn" not in ul:
        return False
    if "/learn" not in ul:
        return False

    # 丢弃明显的非内容页
    deny_substrings = [
        "/learn?",
        "/learn#",
        "page=",
        "pagesize=",
        "sort=",
        "filter=",
        "search",
        "login",
        "signup",
        "register",
        "account",
        "settings",
        "tag/",
        "tags/",
        "topic/",
        "topics/",
        "category",
        "categories",
    ]
    if any(x in ul for x in deny_substrings):
        return False

    # 保守：要求路径层级更深一点（避免把 /learn 或 /learn/xxx 这种栏目页塞进来）
    try:
        path = ul.split("modelscope.cn", 1)[1].split("?", 1)[0].split("#", 1)[0]
        parts = [p for p in path.split("/") if p]
        if len(parts) < 3:  # e.g. ["learn"] or ["learn","xxx"]
            return False
    except Exception:
        pass

    return True


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
            all_hrefs_found = 0
            filtered_out = 0
            for m in _A_HREF_TEXT_RE.finditer(html):
                href = (m.group("href") or "").strip()
                if not href or href.startswith("#"):
                    continue
                abs_url = urljoin(str(url), href)
                all_hrefs_found += 1
                if not _is_modelscope_learn_article_url(abs_url):
                    filtered_out += 1
                    continue

                anchor_text = _strip_html(m.group("text") or "")
                # 过滤掉过短/明显不是标题的锚文本
                if len(anchor_text) < 6:
                    filtered_out += 1
                    continue
                if anchor_text.lower() in {"learn", "more", "read more", "详情"}:
                    filtered_out += 1
                    continue
                if anchor_text in {"首页", "上一页", "下一页", "下一篇", "上一篇", "更多", "查看全部"}:
                    filtered_out += 1
                    continue

                published_at = _find_first_date_near(html, m.start())
                # summary：宁可空，也不要拼接大量噪音
                summary = ""

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
                sample = " / ".join(it["title"][:40] for it in items[:3])
                log.info(
                    "抓取成功（html_list/列表页）：source=%s entries=%d hrefs_found=%d filtered_out=%d 样本标题=[%s]",
                    name, len(items), all_hrefs_found, filtered_out, sample,
                )
                return items, None

            # 走到这里说明正则一条都没提取到——ModelScope Learn 很可能是 SPA，
            # 服务端返回的 HTML 骨架里没有文章链接
            if all_hrefs_found == 0:
                log.warning(
                    "ModelScope Learn 未找到任何 <a href> 链接（html_len=%d）。"
                    "页面很可能是 SPA（React/Vue），静态 HTML 抓取无效。"
                    "将回退到单页兜底，但效果极差，建议改用 API 或 RSS 接入。"
                    " source=%s url=%s",
                    len(html), name, url,
                )
            else:
                log.warning(
                    "ModelScope Learn 找到 %d 个 href，但全部被过滤（filtered_out=%d），"
                    "无有效文章链接。将回退到单页兜底。source=%s url=%s",
                    all_hrefs_found, filtered_out, name, url,
                )

        # ---------------------------
        # Volcengine LLMScan：固定单页，URL 不变，首次推送后会被 sent_items 永久去重。
        # 当前已在 sources.yaml 中 enabled: false，此分支仅作保留以便未来参考。
        # ---------------------------
        if "volcengine" in url_l or "llmscan" in name_l:
            log.warning(
                "html_list 单页兜底（固定URL）：source=%s url=%s "
                "注意：此源 URL 不变，首次推送后将永久被 sent_items 去重屏蔽。",
                name, url,
            )
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
            log.info("抓取成功（html_list/单页）：source=%s entries=%d", name, len(items))
            return items, None

        # ---------------------------
        # Ant Group AI Safety News：固定单篇文章 URL，非新闻列表页。
        # 当前已在 sources.yaml 中 enabled: false，此分支仅作保留以便未来参考。
        # ---------------------------
        if "antgroup" in url_l or "ant group" in name_l:
            log.warning(
                "html_list 单页兜底（固定URL）：source=%s url=%s "
                "注意：此源 URL 不变，首次推送后将永久被 sent_items 去重屏蔽。",
                name, url,
            )
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
            log.info("抓取成功（html_list/单页）：source=%s entries=%d", name, len(items))
            return items, None

        # 默认：单页兜底（未匹配任何已知分支）
        log.warning(
            "html_list 未匹配任何已知处理分支，使用默认单页兜底：source=%s url=%s "
            "title=%r summary_len=%d published_at=%s",
            name, url, title, len(desc), published_at_page,
        )
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

        log.info("抓取成功（html_list/单页兜底）：source=%s entries=%d", name, len(items))
        return items, None
    except HttpError as e:
        msg = f"抓取失败（HTTP）：source={name} url={url} err={e}"
        log.error(msg)
        return [], msg
    except Exception as e:  # noqa: BLE001
        msg = f"抓取失败（未知错误）：source={name} url={url} err={repr(e)}"
        log.exception(msg)
        return [], msg

