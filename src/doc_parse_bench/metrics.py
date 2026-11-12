"""Historical title metric, raw metric extraction and explicitly named aggregations."""

import math
import re
import unicodedata

import Levenshtein

AGENTBUILDER_WEIGHTS = {
    "text_accuracy": 0.3,
    "table_teds": 0.3,
    "reading_order_accuracy": 0.3,
    "title": 0.1,
}

AGENTBUILDER_V2_WEIGHTS = {
    "text_accuracy": 0.3,
    "table_teds": 0.3,
    "reading_order_accuracy": 0.3,
    "title_tree_v2": 0.1,
}


def agentbuilder_v2_score(metrics: dict, source_backend: str) -> float | None:
    """Fixed weights; require all four scores and the Omni page content evaluator."""
    if source_backend != "OmniDocBench":
        raise ValueError("AgentBuilder-v2 的内容分项必须来自 OmniDocBench")
    scores = {key: finite(metrics.get(key)) for key in AGENTBUILDER_V2_WEIGHTS}
    if any(value is None for value in scores.values()):
        return None
    if any(not 0 <= value <= 1 for value in scores.values()):
        raise ValueError("AgentBuilder-v2 分项必须位于 [0,1]")
    return sum(scores[key] * weight for key, weight in AGENTBUILDER_V2_WEIGHTS.items())


def agentbuilder_score(metrics: dict) -> float | None:
    """Aggregate the selected page metrics; a computed zero is a present score."""
    present = {
        key: (value, weight)
        for key, weight in AGENTBUILDER_WEIGHTS.items()
        if (value := finite(metrics.get(key))) is not None
    }
    return (
        round(
            sum(value * weight for value, weight in present.values())
            / sum(weight for _, weight in present.values()),
            4,
        )
        if present
        else None
    )


def normalize_report_metrics(metrics: dict, backend: str) -> dict:
    """Normalize old and new reports without admitting other backends to AgentBuilder."""
    backend = "legacy_compat" if backend == "legacy" else backend
    if backend not in {"OmniDocBench", "MPDocBench", "legacy_compat"}:
        raise ValueError(f"未知评测器：{backend}")
    result = dict(metrics)
    former_score = result.get("agentbuilder_overall")
    result["agentbuilder_overall"] = (
        agentbuilder_score(result) if backend == "OmniDocBench" else None
    )
    if backend == "legacy_compat" and result.get("historical_weighted_overall") is None:
        result["historical_weighted_overall"] = (
            finite(former_score) if finite(former_score) is not None else agentbuilder_score(result)
        )
    required = ("text_accuracy", "formula_cdm", "table_teds")
    scores = [finite(result.get(key)) for key in required]
    result["omnidocbench_overall"] = (
        sum(scores) / 3
        if backend == "OmniDocBench" and all(score is not None for score in scores)
        else None
    )
    mp_modules = (
        "text_edit",
        "merged_text_edit",
        "formula_cdm",
        "table_teds",
        "merged_table_teds",
        "figure_f1",
        "reading_order_edit",
        "head_teds",
    )
    mp_scores = [finite(result.get(name)) for name in mp_modules]
    result["mpdocbench_overall"] = (
        sum(
            1 - score if name.endswith("_edit") else score
            for name, score in zip(mp_modules, mp_scores)
        )
        / len(mp_modules)
        if backend == "MPDocBench" and all(score is not None for score in mp_scores)
        else None
    )
    return result


def extract_title_lines(markdown: str) -> list[tuple[int, str]]:
    # Preserve the historical ATX extraction, including its whitespace behavior.
    return [
        (len(m[1]), m[2].strip())
        for line in markdown.splitlines()
        if (m := re.match(r"^(#{1,6})\s+(.+)", line.strip()))
    ]


def compute_title_score(
    gt: list[tuple[int, str]],
    pred: list[tuple[int, str]],
    level_weight: float = 0.3,
    content_weight: float = 0.7,
) -> float | None:
    """Exact historical greedy pairing; normalize GT levels, compress pred gaps only."""
    if not gt and not pred:
        return None
    if not gt or not pred:
        return 0.0

    def clean(value):
        return "".join(c for c in value if unicodedata.category(c)[0] not in ("Z", "P", "S"))

    def similarity(a, b):
        a, b = clean(a), clean(b)
        return 1 - Levenshtein.distance(a, b) / max(len(a), len(b)) if a or b else 1.0

    gt_levels = [level - min(level for level, _ in gt) + 1 for level, _ in gt]
    ranks = {level: n + 1 for n, level in enumerate(sorted({level for level, _ in pred}))}
    pred_levels = [ranks[level] for level, _ in pred]
    pairs = sorted(
        [(similarity(a, b), i, j) for i, (_, a) in enumerate(gt) for j, (_, b) in enumerate(pred)],
        key=lambda x: x[0],
        reverse=True,
    )
    used_gt, used_pred = set(), set()
    level_sum, content_sum = 0, 0.0
    for score, i, j in pairs:
        if i in used_gt or j in used_pred:
            continue
        used_gt.add(i)
        used_pred.add(j)
        level_sum += gt_levels[i] == pred_levels[j]
        content_sum += score
    denominator = max(len(gt), len(pred))
    return round((level_sum * level_weight + content_sum * content_weight) / denominator, 4)


def finite(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def summarize(raw: dict, title: float | None, backend: str = "OmniDocBench") -> dict:
    """Keep original distances and similarities; never substitute formula edit for CDM."""
    metrics = {}
    module_names = {
        "text_block": "text",
        "reading_order": "reading_order",
        "table": "table",
        "display_formula": "formula",
        "merged_text_block": "merged_text",
        "merged_table": "merged_table",
        "head": "head",
        "figure": "figure",
        "table_relation": "table_relation",
        "text_relation": "text_relation",
    }
    for module, name in module_names.items():
        values = raw.get(module, {}).get("all", {})
        for metric, suffix, key in (
            ("Edit_dist", "edit", "ALL_page_avg"),
            ("TEDS", "teds", "all"),
            ("TEDS_structure_only", "teds_s", "all"),
            ("HeadTEDS", "teds", "all"),
            ("CDM", "cdm", "all"),
            ("FigureF1", "f1", "all"),
            ("Relation_F1", "f1", "all"),
            ("Relation_F1_cross_page", "cross_page_f1", "all"),
            ("Relation_F1_same_page", "same_page_f1", "all"),
        ):
            obj = values.get(metric, {})
            score = finite(obj.get(key)) if isinstance(obj, dict) else finite(obj)
            if score is not None:
                metrics[f"{name}_{suffix}"] = score
                if suffix == "edit":
                    metrics[f"{name}_accuracy"] = 1 - score
    metrics["title"] = title
    return normalize_report_metrics(metrics, backend)
