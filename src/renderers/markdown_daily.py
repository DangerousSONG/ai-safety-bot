import logging
from collections import defaultdict
from typing import Any, Dict, List

from src.utils.time import format_dt, today_ymd


log = logging.getLogger(__name__)


def render_daily_markdown(
    items: List[Dict[str, Any]],
    *,
    tz_name: str,
    title_prefix: str,
    stats: Dict[str, Any],
) -> str:
    date_str = today_ymd(tz_name)
    title = f"{title_prefix}（{date_str}）"

    total_sources = int(stats.get("total_sources", 0))
    ok_sources = int(stats.get("ok_sources", 0))
    failed_sources: List[str] = list(stats.get("failed_sources", []) or [])
    total_fetched = int(stats.get("total_fetched", 0))
    total_candidates = int(stats.get("total_candidates", 0))

    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## 概览")
    lines.append(f"- 抓取源：{ok_sources}/{total_sources} 成功")
    lines.append(f"- 抓取条目：{total_fetched}")
    lines.append(f"- 入选条目：{total_candidates}")
    if failed_sources:
        lines.append(f"- 抓取失败源：{', '.join(failed_sources)}")
    lines.append("")

    if not items:
        lines.append("## 今日精选")
        lines.append("")
        lines.append("今日高相关动态较少（或信息源更新不多）。你可以：")
        lines.append("- 明天再看一轮")
        lines.append("- 或提高抓取条数/降低阈值（见 `configs/rules.yaml`）")
        lines.append("")
        return "\n".join(lines)

    summary_max_chars = int(stats.get("summary_max_chars", 160) or 160)

    # 先按 category 分组，再按 source 分组
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for it in items:
        by_cat[it.get("category") or "未分类"].append(it)

    lines.append("## 今日精选")
    lines.append("")

    for cat in sorted(by_cat.keys()):
        lines.append(f"### {cat}")
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for it in by_cat[cat]:
            groups[it.get("source_name") or "未知来源"].append(it)

        for src in sorted(groups.keys()):
            lines.append(f"- **{src}**")
            for it in groups[src]:
                title = it.get("title", "").strip()
                url = it.get("url", "").strip()
                pub = format_dt(it.get("published_at"), tz_name=tz_name)
                score = it.get("score", 0)
                summary = (it.get("summary") or "").strip()
                if summary and len(summary) > summary_max_chars:
                    summary = summary[: summary_max_chars - 1].rstrip() + "…"

                reason = it.get("reason") or {}
                strong = reason.get("strong") or []
                weak = reason.get("weak") or []
                ai_ctx = reason.get("ai_context") or []
                reason_parts: List[str] = []
                if strong:
                    reason_parts.append("强关键词：" + "、".join(str(x) for x in strong[:5]))
                if ai_ctx:
                    reason_parts.append("AI上下文：" + "、".join(str(x) for x in ai_ctx[:3]))
                if weak:
                    reason_parts.append("弱关键词：" + "、".join(str(x) for x in weak[:5]))
                reason_text = "；".join(reason_parts) if reason_parts else "规则命中"

                suffix_parts: List[str] = []
                if pub:
                    suffix_parts.append(pub)
                suffix_parts.append(f"score={score}")
                suffix = "；".join(suffix_parts)
                lines.append(f"  - [{title}]({url})（{suffix}）")
                lines.append(f"    - 入选原因：{reason_text}")
                if summary:
                    lines.append(f"    - 摘要：{summary}")
        lines.append("")

    return "\n".join(lines)

