import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


log = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """
    轻量 URL 规范化：去 fragment、清理常见追踪参数、规范 scheme/host 小写。
    """
    u = (url or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        scheme = (p.scheme or "").lower()
        netloc = (p.netloc or "").lower()
        path = p.path or ""

        # 清理常见追踪参数（保守一些，避免误删业务参数）
        qs = []
        for k, v in parse_qsl(p.query, keep_blank_values=True):
            kl = k.lower()
            if kl.startswith("utm_"):
                continue
            if kl in {"ref", "source", "spm", "from"}:
                continue
            qs.append((k, v))
        query = urlencode(qs, doseq=True)

        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:  # noqa: BLE001
        return u


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def build_item_id(
    *,
    source_name: str,
    url: str,
    title: str,
    published_at: Optional[datetime],
) -> str:
    """
    生成唯一 ID：
    1) 优先 source + normalized_url
    2) 若无 url，则 source + title + published_at
    """
    src = (source_name or "").strip().lower()
    nurl = normalize_url(url)
    if nurl:
        return _sha1(f"url|{src}|{nurl}")

    pub = ""
    if published_at:
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        pub = published_at.astimezone(timezone.utc).isoformat()
    t = (title or "").strip().lower()
    return _sha1(f"fallback|{src}|{t}|{pub}")


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def load_sent_items(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        if not isinstance(data, dict):
            return {"items": []}
        if not isinstance(data.get("items"), list):
            data["items"] = []
        return data
    except Exception as e:  # noqa: BLE001
        log.warning("读取 sent_items 失败，将视为无历史：path=%s err=%r", path, e)
        return {"items": []}


def prune_sent_items(data: Dict[str, Any], *, keep_days: int = 90) -> Dict[str, Any]:
    items = list(data.get("items") or [])
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)

    kept: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        first_sent_at = _parse_dt(str(it.get("first_sent_at", "")))
        if first_sent_at and first_sent_at >= cutoff:
            kept.append(it)
        elif not first_sent_at:
            # 没有时间的旧记录直接丢弃，避免状态文件膨胀
            continue
    data["items"] = kept
    return data


def sent_id_set(data: Dict[str, Any]) -> set[str]:
    s: set[str] = set()
    for it in data.get("items") or []:
        if isinstance(it, dict) and it.get("id"):
            s.add(str(it["id"]))
    return s


def upsert_sent_items(
    data: Dict[str, Any],
    *,
    pushed_items: Iterable[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    将本次“已推送”的条目写入状态文件（仅新增，不覆盖旧 first_sent_at）。
    """
    now = now or datetime.now(timezone.utc)
    now_s = now.astimezone(timezone.utc).isoformat()

    items: List[Dict[str, Any]] = list(data.get("items") or [])
    index: Dict[str, Dict[str, Any]] = {}
    for it in items:
        if isinstance(it, dict) and it.get("id"):
            index[str(it["id"])] = it

    added = 0
    for it in pushed_items:
        iid = str(it.get("id") or "")
        if not iid:
            continue
        if iid in index:
            continue

        pub = it.get("published_at")
        pub_s = ""
        if isinstance(pub, datetime):
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            pub_s = pub.astimezone(timezone.utc).isoformat()

        rec = {
            "id": iid,
            "source": it.get("source_name", ""),
            "title": it.get("title", ""),
            "url": it.get("url", ""),
            "published_at": pub_s,
            "first_sent_at": now_s,
        }
        items.append(rec)
        index[iid] = rec
        added += 1

    data["items"] = items
    log.info("sent_items 更新：added=%d total=%d", added, len(items))
    return data


def save_sent_items(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")

