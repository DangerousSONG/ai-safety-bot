import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml

from src.collectors.feed_collector import fetch_feed_entries
from src.filters.relevance import filter_and_rank
from src.notifiers.feishu import FeishuError, send_daily_report
from src.renderers.markdown_daily import render_daily_markdown
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

    log.info("启动：repo_root=%s", repo_root)
    sources_cfg = load_yaml(sources_path)
    rules_cfg = load_yaml(rules_path)

    sources: List[Dict[str, Any]] = list(sources_cfg.get("sources", []) or [])
    relevance_rules: Dict[str, Any] = dict(rules_cfg.get("relevance", {}) or {})
    output_cfg: Dict[str, Any] = dict(rules_cfg.get("output", {}) or {})

    tz_name = str(output_cfg.get("timezone", "Asia/Shanghai"))
    title_prefix = str(output_cfg.get("title_prefix", "AI 安全日报"))
    date_str = today_ymd(tz_name)

    enabled_sources = [s for s in sources if bool(s.get("enabled", True))]
    log.info("信息源：total=%d enabled=%d", len(sources), len(enabled_sources))

    per_source_max_entries = int(relevance_rules.get("per_source_max_entries", 30))
    all_items: List[Dict[str, Any]] = []
    failed_sources: List[str] = []
    ok_sources = 0
    total_fetched = 0

    for src in enabled_sources:
        if src.get("type") != "feed":
            log.warning(
                "跳过非 feed 源（第一版不支持）：name=%s type=%s",
                src.get("name"),
                src.get("type"),
            )
            continue

        entries, err = fetch_feed_entries(src, max_entries=per_source_max_entries)
        if err:
            failed_sources.append(str(src.get("name", "unknown")))
            log.warning("抓取失败：source=%s err=%s", src.get("name"), err)
            continue

        ok_sources += 1
        total_fetched += len(entries)
        all_items.extend(entries)

    ranked = filter_and_rank(all_items, relevance_rules)
    top_n = int(relevance_rules.get("top_n", 10))
    picked = ranked[:top_n]

    stats = {
        "total_sources": len(enabled_sources),
        "ok_sources": ok_sources,
        "failed_sources": failed_sources,
        "total_fetched": total_fetched,
        "total_candidates": len(picked),
    }

    md = render_daily_markdown(
        picked,
        tz_name=tz_name,
        title_prefix=title_prefix,
        stats=stats,
    )

    save_output(repo_root, md)

    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    feishu_secret = os.getenv("FEISHU_BOT_SECRET", "").strip()
    feishu_title = f"{title_prefix}（{date_str}）"

    try:
        send_daily_report(
            webhook_url=webhook,
            title=feishu_title,
            markdown_text=md,
            secret=feishu_secret or None,
        )
    except FeishuError as e:
        log.error("推送失败：%s", e)
        log.info("日报内容如下：\n%s", md)
        return 2

    log.info("完成：picked=%d failed_sources=%d", len(picked), len(failed_sources))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())