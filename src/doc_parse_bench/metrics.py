"""Historical title metric, raw metric extraction and explicitly named aggregations."""

import math
import re
import unicodedata

import Levenshtein


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


def summarize(raw: dict, title: float | None) -> dict:
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
    weights = {"text_accuracy": 0.3, "table_teds": 0.3, "reading_order_accuracy": 0.3, "title": 0.1}
    present = {key: value for key, value in weights.items() if metrics.get(key) is not None}
    metrics["agentbuilder_overall"] = (
        round(sum(metrics[k] * w for k, w in present.items()) / sum(present.values()), 4)
        if present
        else None
    )
    # Official v1.5+ Overall averages text accuracy, FormulaCDM and table TEDS.
    # Reading order and the custom title score are reported separately.
    required = ("text_accuracy", "formula_cdm", "table_teds")
    metrics["omnidocbench_overall"] = (
        sum(metrics[k] for k in required) / 3 if all(k in metrics for k in required) else None
    )
    return metrics
