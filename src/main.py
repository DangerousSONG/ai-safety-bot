import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml

from src.collectors.feed_collector import fetch_feed_entries
from src.collectors.html_list_collector import fetch_html_list_entries
from src.filters.relevance import filter_and_rank
from src.notifiers.feishu import FeishuError, send_daily_report
from src.renderers.markdown_daily import render_daily_markdown
from src.store.sent_items import (
    build_item_id,
    load_sent_items,
    prune_sent_items,
    save_sent_items,
    sent_id_set,
    upsert_sent_items,
)
from src.utils.time import today_ymd


def setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


log = logging.getLogger(__name__)


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML 顶层必须是 dict：{path}")
    return data


def save_output(repo_root: Path, content: str) -> None:
    """
    保存最近一次生成的日报，便于本地调试和 Actions 排查。
    """
    outputs_dir = repo_root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    output_file = outputs_dir / "daily_latest.md"
    output_file.write_text(content, encoding="utf-8")


def main() -> int:
    setup_logging()

    repo_root = Path(__file__).resolve().parent.parent
    sources_path = repo_root / "configs" / "sources.yaml"
    rules_path = repo_root / "configs" / "rules.yaml"
    sent_path = repo_root / "data" / "sent_items.json"

    log.info("启动：repo_root=%s", repo_root)
    sources_cfg = load_yaml(sources_path)
    rules_cfg = load_yaml(rules_path)

    sources: List[Dict[str, Any]] = list(sources_cfg.get("sources", []) or [])
    relevance_rules: Dict[str, Any] = dict(rules_cfg.get("relevance", {}) or {})
    output_cfg: Dict[str, Any] = dict(rules_cfg.get("output", {}) or {})

    tz_name = str(output_cfg.get("timezone", "Asia/Shanghai"))
    title_prefix = str(output_cfg.get("title_prefix", "AI 安全日报"))
    summary_max_chars = int(output_cfg.get("summary_max_chars", 160))
    date_str = today_ymd(tz_name)

    enabled_sources = [s for s in sources if bool(s.get("enabled", True))]
    log.info("信息源：total=%d enabled=%d", len(sources), len(enabled_sources))

    sent_data = prune_sent_items(load_sent_items(sent_path), keep_days=90)
    sent_ids = sent_id_set(sent_data)
    log.info("历史已推送：count=%d（保留90天）", len(sent_ids))

    per_source_max_entries = int(relevance_rules.get("per_source_max_entries", 30))
    all_items: List[Dict[str, Any]] = []
    failed_sources: List[str] = []
    ok_sources = 0
    total_fetched = 0

    for src in enabled_sources:
        stype = src.get("type")
        if stype == "feed":
            recency_days = int(relevance_rules.get("recency_days", 30))
            entries, err = fetch_feed_entries(
                src,
                max_entries=per_source_max_entries,
                recency_days=recency_days,
            )
        elif stype == "html_list":
            entries, err = fetch_html_list_entries(
                src,
                max_entries=per_source_max_entries,
            )
        else:
            log.warning("跳过未知类型源：name=%s type=%s", src.get("name"), stype)
            continue

        if err:
            failed_sources.append(str(src.get("name", "unknown")))
            log.warning("抓取失败：source=%s err=%s", src.get("name"), err)
            continue

        ok_sources += 1
        total_fetched += len(entries)
        all_items.extend(entries)

    # 去重：过滤掉历史已推送条目
    kept_items: List[Dict[str, Any]] = []
    skipped = 0
    for it in all_items:
        iid = build_item_id(
            source_name=str(it.get("source_name", "")),
            url=str(it.get("url", "")),
            title=str(it.get("title", "")),
            published_at=it.get("published_at"),
        )
        it["id"] = iid
        if iid in sent_ids:
            skipped += 1
            continue
        kept_items.append(it)
    if skipped:
        log.info("已过滤历史推送：skipped=%d remaining=%d", skipped, len(kept_items))

    ranked = filter_and_rank(kept_items, relevance_rules)

    # per-source 限流：避免单个高产源（如 arXiv）独占日报
    max_per_source = int(relevance_rules.get("max_per_source", 3))
    top_n = int(relevance_rules.get("top_n", 10))
    source_counts: Dict[str, int] = {}
    capped: List[Dict[str, Any]] = []
    for it in ranked:
        sname = str(it.get("source_name", ""))
        if source_counts.get(sname, 0) >= max_per_source:
            continue
        source_counts[sname] = source_counts.get(sname, 0) + 1
        capped.append(it)
    picked = capped[:top_n]

    if len(ranked) != len(capped):
        log.info(
            "per-source 限流（max=%d）：ranked=%d → capped=%d → picked=%d",
            max_per_source, len(ranked), len(capped), len(picked),
        )

    stats = {
        "total_sources": len(enabled_sources),
        "ok_sources": ok_sources,
        "failed_sources": failed_sources,
        "total_fetched": total_fetched,
        "total_candidates": len(picked),
        "recency_days": int(relevance_rules.get("recency_days", 180)),
    }

    body = render_daily_markdown(
        picked,
        tz_name=tz_name,
        title_prefix=title_prefix,
        summary_max_chars=summary_max_chars,
        stats=stats,
    )

    save_output(repo_root, body)

    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    feishu_secret = os.getenv("FEISHU_BOT_SECRET", "").strip()
    feishu_title = f"{title_prefix}（{date_str}）"

    try:
        send_daily_report(
            webhook_url=webhook,
            title=feishu_title,
            markdown_text=body,
            secret=feishu_secret or None,
        )
    except FeishuError as e:
        log.error("推送失败：%s", e)
        log.info("日报内容如下：\n%s", body)
        return 2

    # 推送成功后再写 sent_items，避免“发失败但记录为已发”
    if picked:
        sent_data = upsert_sent_items(sent_data, pushed_items=picked)
        sent_data = prune_sent_items(sent_data, keep_days=90)
        save_sent_items(sent_path, sent_data)

    log.info("完成：picked=%d failed_sources=%d", len(picked), len(failed_sources))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())