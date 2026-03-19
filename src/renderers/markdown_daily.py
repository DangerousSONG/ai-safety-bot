from collections import defaultdict
from typing import Any, Dict, List

from src.utils.time import format_dt, today_ymd


def _shorten(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= max_chars:
        return t
    return t[: max(0, max_chars - 1)].rstrip() + "…"


def _build_reason_text(reason: Dict[str, Any]) -> str:
    strong = reason.get("strong") or []
    weak = reason.get("weak") or []
    ai_ctx = reason.get("ai_context") or []

    parts: List[str] = []
    if strong:
        parts.append("强关键词：" + "、".join(str(x) for x in strong[:5]))
    if ai_ctx:
        parts.append("AI上下文：" + "、".join(str(x) for x in ai_ctx[:3]))
    if weak:
        parts.append("弱关键词：" + "、".join(str(x) for x in weak[:5]))
    return "；".join(parts)


def render_daily_markdown(
    items: List[Dict[str, Any]],
    *,
    tz_name: str,
    title_prefix: str,
    summary_max_chars: int = 160,
    stats: Dict[str, Any],
) -> str:
    """
    虽然函数名保留为 markdown，但第一版飞书使用 text 消息：
    这里输出适合“纯文本展示”的格式（不包含 #/##/** 等 Markdown 标记）。
    """
    total_sources = int(stats.get("total_sources", 0))
    ok_sources = int(stats.get("ok_sources", 0))
    failed_sources: List[str] = list(stats.get("failed_sources", []) or [])
    total_fetched = int(stats.get("total_fetched", 0))
    total_candidates = int(stats.get("total_candidates", 0))
    recency_days = int(stats.get("recency_days", 180))

    lines: List[str] = []
    overview_parts: List[str] = [
        f"统计窗口：最近{recency_days}天",
        f"抓取源 {ok_sources}/{total_sources}",
        f"抓取 {total_fetched}",
        f"入选 {total_candidates}",
    ]
    if failed_sources:
        overview_parts.append("失败 " + "、".join(failed_sources))
    lines.append("【概览】" + "｜".join(overview_parts))
    lines.append("")

    lines.append("【今日精选】")

    if not items:
        lines.append("今日高相关动态较少（或信息源更新不多）。")
        return "\n".join(lines)

    summary_max_chars = int(summary_max_chars or 160)

    # 按 category 分组，组内按顺序输出
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for it in items:
        by_cat[it.get("category") or "未分类"].append(it)

    idx = 0
    for cat in sorted(by_cat.keys()):
        lines.append("")
        lines.append(f"【{cat}】")

        for it in by_cat[cat]:
            idx += 1
            t = _shorten(it.get("title", ""), 140)
            url = (it.get("url", "") or "").strip()
            pub = format_dt(it.get("published_at"), tz_name=tz_name)
            summary = _shorten(it.get("summary", ""), summary_max_chars)
            score = it.get("score", 0)
            reason_text = _build_reason_text(it.get("reason") or {})

            # 每条新闻统一格式：
            # 标题 / 时间 / 简要提炼 / 入选原因 / 原文链接
            lines.append(f"{idx}. 标题：{t}")
            if pub:
                lines.append(f"   时间：{pub}")
            if summary:
                lines.append(f"   简要提炼：{summary}")
            if reason_text:
                lines.append(f"   入选原因：{reason_text}（score={score}）")
            else:
                lines.append(f"   入选原因：规则命中（score={score}）")
            if url:
                lines.append(f"   原文链接：{url}")

    return "\n".join(lines)

