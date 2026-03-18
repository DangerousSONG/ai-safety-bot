import logging
from typing import Any, Dict, List, Tuple


log = logging.getLogger(__name__)


def _lower(s: str) -> str:
    return (s or "").lower()


def score_title(title: str, rules: Dict[str, Any]) -> Tuple[int, List[str]]:
    """
    第一版：只基于标题做相关性打分。
    返回 (score, matched_keywords)。
    """
    scoring = rules.get("scoring", {}) or {}
    strong_hit = int(scoring.get("strong_hit", 4))
    weak_hit = int(scoring.get("weak_hit", 1))
    ai_context_hit = int(scoring.get("ai_context_hit", 1))
    deny_hit = int(scoring.get("deny_hit", -100))

    strong_keywords = rules.get("strong_keywords", []) or []
    weak_keywords = rules.get("weak_keywords", []) or []
    ai_context_keywords = rules.get("ai_context_keywords", []) or []
    deny_keywords = rules.get("deny_keywords", []) or []

    t = _lower(title)
    matched: List[str] = []

    for kw in deny_keywords:
        if _lower(str(kw)) in t:
            matched.append(str(kw))
            return deny_hit, matched

    score = 0

    ai_ctx = False
    for kw in ai_context_keywords:
        if _lower(str(kw)) in t:
            ai_ctx = True
            matched.append(str(kw))
            score += ai_context_hit
            break

    for kw in strong_keywords:
        if _lower(str(kw)) in t:
            matched.append(str(kw))
            score += strong_hit

    # 弱相关词：需要与 AI 上下文同现才加分（避免“泛安全”噪声）
    if ai_ctx:
        for kw in weak_keywords:
            if _lower(str(kw)) in t:
                matched.append(str(kw))
                score += weak_hit

    return score, matched


def filter_and_rank(items: List[Dict[str, Any]], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    过滤 + 排序：
    - score >= min_score 保留
    - score 降序，其次发布时间降序（若有）
    """
    min_score = int(rules.get("min_score", 3))

    kept: List[Dict[str, Any]] = []
    for it in items:
        title = it.get("title", "")
        score, matched = score_title(title, rules)
        it2 = dict(it)
        it2["score"] = score
        it2["matched_keywords"] = matched

        if score >= min_score:
            kept.append(it2)

    kept.sort(key=lambda x: (int(x.get("score", 0)), x.get("published_at") or 0), reverse=True)
    log.info("筛选完成：input=%d kept=%d min_score=%d", len(items), len(kept), min_score)
    return kept

