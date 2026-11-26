"""Score reviewed feature evidence against a frozen GT manifest."""

import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean

from ..io import fresh_directory, read_json, sha256, write_json
from .feature_contract import FEATURES, PAIRS

GT_SCHEMA = "doc-parse-bench.feature-rubric-gt.v1"
EVIDENCE_SCHEMA = "doc-parse-bench.feature-rubric-evidence.v1"
RUBRIC_VERSION = "legacy129-content"
CONFIG = {"mineru_provider": "mineru3", "relevel_titles": True, "title_rules": False}
IMAGE_GROUPS = ("text_image", "flowchart", "natural_image", "seal")
EDGE_TYPES = {"header", "footer", "page_number", "header_image", "footer_image"}
PROTECTION_STATES = {"complete", "partial", "missing"}
DECIMAL_VALUE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def _index(rows: list[dict], key: str = "id") -> dict:
    indexed = {}
    for row in rows:
        value = row[key]
        if not isinstance(value, str) or not value.strip() or value in indexed:
            raise ValueError(f"空或重复的 {key}：{value!r}")
        indexed[value] = row
    return indexed


def _text(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("文本和数值须以字符串提供")
    return "".join(unicodedata.normalize("NFKC", value).split())


def _number(point: dict, *, truth: bool = False) -> tuple[Decimal | str, bool]:
    value = point["value"]
    if not isinstance(value, str):
        raise ValueError("图表数值须以字符串提供")
    normalized = unicodedata.normalize("NFKC", value).strip()
    percent = normalized.endswith("%")
    if percent and (not truth or _text(point["unit"]) == "%"):
        normalized = normalized[:-1].rstrip()
    if DECIMAL_VALUE.fullmatch(normalized):
        try:
            return Decimal(normalized), percent
        except InvalidOperation:
            pass
    if truth:
        raise ValueError(f"明示值 GT 不是有限十进制数：{value!r}")
    return normalized, percent


def _f1(tp: int, fp: int, fn: int) -> float | None:
    denominator = 2 * tp + fp + fn
    return 100 * 2 * tp / denominator if denominator else None


def _counts(expected, observed) -> dict:
    truth, prediction = Counter(expected), Counter(observed)
    tp = sum((truth & prediction).values())
    return _measure(tp, sum(prediction.values()) - tp, sum(truth.values()) - tp)


def _measure(tp: int, fp: int, fn: int) -> dict:
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": 100 * tp / (tp + fp) if tp + fp else None,
        "recall": 100 * tp / (tp + fn) if tp + fn else None,
        "score": _f1(tp, fp, fn),
    }


def _micro(rows: list[dict]) -> dict:
    return _measure(*(sum(row[key] for row in rows) for key in ("tp", "fp", "fn")))


def _coverage(planned: int, scored: int) -> dict:
    """Describe how much of a planned feature has usable score evidence."""
    return {
        "planned": planned,
        "scored": scored,
        "missing": planned - scored,
        "rate": 100 * scored / planned if planned else None,
    }


def _score_status(score: float | None, planned: int, scored: int) -> str:
    if planned == 0:
        return "not_covered"
    if score is None or scored != planned:
        return "pending_evidence"
    return "scored"


def _missing_reasons(case: dict, observation: dict, status: str) -> list[str]:
    if status == "pair_unverified":
        return ["capture_pair_unverified"]
    if status not in {"evidence_missing", "baseline_incomplete"}:
        return []
    if case.get("protected"):
        return ["baseline_incomplete"] if status == "baseline_incomplete" else ["protection_states"]
    if case["feature"] == "appendix":
        required = ("on_anchors", "off_residual")
    elif case["feature"] == "header_footer":
        required = ("on_blocks", "off_residual_ids")
    elif case["feature"] == "chart":
        required = (
            ("table_status", "values")
            if observation.get("table_status") == "parsed"
            else ("table_status",)
        )
    else:
        required = ("fields",)
        if case["sub_type"] != "seal":
            # Explicit null is a confirmed missing label and is a valid zero.
            if "sub_type" not in observation:
                required += ("sub_type",)
        if "relations" in case:
            required += ("relations",)
        if case["sub_type"] == "natural_image" and not case["fields"]:
            required += ("image_available",)
    return [key for key in required if key not in observation or observation[key] is None]


def _verified_pair(case: dict, captures: dict) -> bool:
    groups = captures.get(case["document_id"], {})
    on_group, off_group = PAIRS[case["feature"]]
    on_capture = groups.get(on_group)
    return (
        isinstance(on_capture, str)
        and bool(on_capture.strip())
        and (on_capture == groups.get(off_group))
    )


def _appendix(case: dict, observed: dict) -> dict | None:
    anchors = case["anchors"]
    if not isinstance(anchors, list) or not anchors or len(set(anchors)) != len(anchors):
        raise ValueError("附录页须有不重复的内容锚点列表")
    delivered = observed.get("on_anchors")
    residual = observed.get("off_residual")
    if delivered is None or residual is None:
        return None
    if not isinstance(delivered, list) or type(residual) is not bool:
        raise ValueError("附录证据需要 on_anchors 列表与 off_residual 布尔值")
    if set(delivered) - set(anchors):
        raise ValueError("附录开启证据含未知锚点")
    missing = sorted(set(anchors) - set(delivered))
    return {
        "score": 100.0 if not missing and not residual else 0.0,
        "on_complete": not missing,
        "off_residual": residual,
        "missing_anchors": missing,
    }


def _edge_value(block: dict, kind: str):
    if kind.endswith("_image"):
        return block.get("image_available") is True
    value = _text(block.get("text", ""))
    return int(value) if kind == "page_number" and value.isdecimal() else value


def _header_footer(case: dict, observed: dict) -> dict | None:
    expected = _index(case["blocks"])
    delivered = observed.get("on_blocks")
    remaining = observed.get("off_residual_ids")
    if delivered is None or remaining is None:
        return None
    if not isinstance(delivered, list) or not isinstance(remaining, list):
        raise ValueError("页眉页脚证据须提供 on_blocks 和 off_residual_ids 列表")
    residual = set(remaining)
    if residual - expected.keys():
        raise ValueError("页眉页脚关闭证据含未知块 ID")
    correct, seen, extra = set(), set(), []
    for prediction_id, block in _index(delivered).items():
        source_id = block.get("source_id")
        truth = expected.get(source_id)
        if source_id is not None and truth is None:
            raise ValueError(f"页眉页脚开启证据含未知块 ID：{source_id}")
        if truth is not None:
            seen.add(source_id)
            kind = truth["type"]
            reference = True if kind.endswith("_image") else _edge_value(truth, kind)
            if source_id not in correct and _edge_value(block, kind) == reference:
                correct.add(source_id)
                continue
        extra.append(prediction_id)
    hits = correct - residual
    return _measure(len(hits), len(extra), len(expected) - len(hits)) | {
        "blocks": {
            source_id: {
                "type": block["type"],
                "on_seen": source_id in seen,
                "on_correct": source_id in correct,
                "off_residual": source_id in residual,
                "hit": source_id in hits,
            }
            for source_id, block in expected.items()
        },
        "false_positive_ids": extra,
    }


def _subtype(case: dict, observed: dict) -> dict:
    expected = case["sub_type"]
    actual = observed.get("sub_type")
    if "sub_type" not in observed:
        status = "evidence_missing"
    elif actual is None:
        status = "missing"
    else:
        if not isinstance(actual, str) or not actual.strip():
            raise ValueError("预测 sub_type 必须是实际标签或 null")
        if not isinstance(observed.get("subtype_id"), str) or not observed["subtype_id"].strip():
            raise ValueError("实际 sub_type 需要可追溯的 subtype_id")
        status = "correct" if actual == expected else "wrong"
    return {"expected": expected, "observed": actual, "status": status}


def _field(row: dict) -> tuple[str, str]:
    return row["key"], _text(row["text"])


def _relation(row: dict) -> tuple[str, str]:
    return row["from"], row["to"]


def _image(case: dict, observed: dict) -> dict:
    kind = case["sub_type"]
    subtype = None if kind == "seal" else _subtype(case, observed)
    if kind == "other":
        return {"score": None, "subtype": subtype}
    content, fields, relations = None, None, None
    if observed.get("fields") is not None:
        reference = list(map(_field, case["fields"]))
        prediction = list(map(_field, observed["fields"]))
        fields = _counts(reference, prediction)
        content = fields["score"]
        if not case["fields"]:
            available = observed.get("image_available")
            if available is not None and type(available) is not bool:
                raise ValueError("image_available 须是布尔值")
            content = None if available is None else 100.0 * (available and fields["fp"] == 0)
    if "relations" in case:
        if content is None or observed.get("relations") is None:
            content = None
        else:
            matched_nodes = {key for key, _ in set(reference) & set(prediction)}
            predicted_edges = list(map(_relation, observed["relations"]))
            aligned_edges = [edge for edge in predicted_edges if set(edge) <= matched_nodes]
            relations = _counts(map(_relation, case["relations"]), aligned_edges)
            relations = _measure(
                relations["tp"], len(predicted_edges) - relations["tp"], relations["fn"]
            )
            relation_score = relations["score"] if relations["score"] is not None else 100.0
            content = 0.6 * content + 0.4 * relation_score
    score = content
    if subtype is not None and subtype["status"] != "correct":
        score = None if subtype["status"] == "evidence_missing" else 0.0
    return {
        "score": score,
        "content_score": content,
        "subtype": subtype,
        "fields": fields,
        "relations": relations,
        "stratum": (
            ("photo_with_text" if case["fields"] else "photo_without_text")
            if kind == "natural_image"
            else kind
        ),
    }


def _chart_slot(row: dict) -> tuple[str, str, str]:
    return _text(row["series"]), _text(row["category"]), _text(row["unit"])


def _maximum_weight_pairs(weights: list[list[int]]) -> list[tuple[int, int]]:
    """Find a maximum weight one-to-one assignment with the Hungarian algorithm."""
    if not weights or not weights[0]:
        return []
    actual_columns = len(weights[0])
    column_count = max(actual_columns, len(weights))
    row_potential = [0] * (len(weights) + 1)
    column_potential = [0] * (column_count + 1)
    owners = [0] * (column_count + 1)
    for row in range(1, len(weights) + 1):
        owners[0] = row
        current = 0
        predecessor = [0] * (column_count + 1)
        distances = [float("inf")] * (column_count + 1)
        visited = [False] * (column_count + 1)
        while True:
            visited[current] = True
            active_row = owners[current]
            step, next_column = float("inf"), 0
            for candidate in range(1, column_count + 1):
                if visited[candidate]:
                    continue
                weight = (
                    weights[active_row - 1][candidate - 1] if candidate <= actual_columns else 0
                )
                cost = -weight - row_potential[active_row] - column_potential[candidate]
                if cost < distances[candidate]:
                    distances[candidate] = cost
                    predecessor[candidate] = current
                if distances[candidate] < step:
                    step, next_column = distances[candidate], candidate
            for candidate, seen in enumerate(visited):
                if seen:
                    row_potential[owners[candidate]] += step
                    column_potential[candidate] -= step
                else:
                    distances[candidate] -= step
            current = next_column
            if not owners[current]:
                break
        while current:
            previous = predecessor[current]
            owners[current] = owners[previous]
            current = previous
    return [
        (row - 1, column - 1)
        for column, row in enumerate(owners[1 : actual_columns + 1], start=1)
        if row and weights[row - 1][column - 1]
    ]


def _chart_category(category: str) -> str:
    return re.sub(r"^([0-9]{4})年$", r"\1", category)


def _observed_chart_columns(observed: dict) -> dict:
    points = observed.get("values") or []
    column_ids = [point.get("column_id") for point in points]
    if any("column_id" in point for point in points):
        if any(not isinstance(column_id, str) or not column_id.strip() for column_id in column_ids):
            raise ValueError("各数据项须提供其实际输出列的 column_id")
    elif observed.get("block_id"):
        prefix = f"{observed['block_id']}:"
        positions = [
            re.fullmatch(r"[0-9]+:([0-9]+)", point["id"][len(prefix) :])
            if point["id"].startswith(prefix)
            else None
            for point in points
        ]
        if all(positions):
            column_ids = [f"{prefix}{position[1]}" for position in positions]

    columns = {}
    for point, column_id in zip(points, column_ids):
        series, category, unit = _chart_slot(point)
        header = series, unit
        column_header, bare_cells, percent_cells = columns.setdefault(
            column_id or header, (header, Counter(), Counter())
        )
        if header != column_header:
            raise ValueError(f"同一输出列的表头和单位须一致：{column_id}")
        number, percent = _number(point)
        cells = percent_cells if percent else bare_cells
        cells[_chart_category(category), number] += 1
    return columns


def _chart_column_values(expected: dict, unscored_slots: set, observed: dict) -> dict:
    truth = defaultdict(Counter)
    for (series, category, unit), value in expected.items():
        truth[series, unit][_chart_category(category), value] += 1
    predicted = _observed_chart_columns(observed)
    known_headers = set(truth) | {(series, unit) for series, unit, _ in unscored_slots}
    known_series = {series for series, _ in known_headers if series}
    series_with_unit = {
        f"{series}({unit})": series for series, unit in sorted(known_headers) if series and unit
    }

    def header_conflicts(
        expected_header: tuple[str, str], actual_header: tuple[str, str]
    ) -> list[str]:
        expected_series, expected_unit = expected_header
        actual_series, actual_unit = actual_header
        recognized_series = (
            actual_series if actual_series in known_series else series_with_unit.get(actual_series)
        )
        conflicts = []
        if recognized_series and recognized_series != expected_series:
            conflicts.append("series")
        if expected_unit and actual_unit and actual_unit != expected_unit:
            conflicts.append("unit")
        return conflicts

    source_headers = list(truth)
    output_ids = list(predicted)
    overlaps, conflicts, weights = [], [], []
    for source in source_headers:
        row_hits, row_conflicts, row_weights = [], [], []
        for output_id in output_ids:
            actual_header, bare_cells, percent_cells = predicted[output_id]
            actual_values = bare_cells + percent_cells if source[1] == "%" else bare_cells
            hits = sum((truth[source] & actual_values).values())
            issues = header_conflicts(source, actual_header)
            row_hits.append(hits)
            row_conflicts.append(issues)
            row_weights.append(hits * (len(source_headers) + 1) + int(bool(hits) and not issues))
        overlaps.append(row_hits)
        conflicts.append(row_conflicts)
        weights.append(row_weights)

    matches = []
    for source_index, output_index in _maximum_weight_pairs(weights):
        source = source_headers[source_index]
        output_id = output_ids[output_index]
        actual_header, _, _ = predicted[output_id]
        matches.append(
            {
                "series": source[0],
                "unit": source[1],
                "column_id": output_id if isinstance(output_id, str) else None,
                "predicted_series": actual_header[0],
                "predicted_unit": actual_header[1],
                "matched_values": overlaps[source_index][output_index],
                "expected_values": sum(truth[source].values()),
                "header_conflicts": conflicts[source_index][output_index],
            }
        )
    hits = sum(match["matched_values"] for match in matches)
    return {
        "score": 100 * hits / len(expected) if expected else None,
        "matched_values": hits,
        "expected_values": len(expected),
        "unmatched_output_cells": len(observed.get("values") or []) - hits,
        "column_matches": matches,
    }


def _chart(case: dict, observed: dict) -> dict | None:
    expected = {_chart_slot(point): _number(point, truth=True)[0] for point in case["values"]}
    if len(expected) != len(case["values"]):
        raise ValueError("同一源图的系列、类别和单位不可重复标值")
    unscored_slots = {
        (
            _text(slot["series"]),
            _text(slot["unit"]),
            _text(slot["category"]) if "category" in slot else None,
        )
        for slot in case.get("unscored", [])
    }

    if any(
        (series, unit, None) in unscored_slots or (series, unit, category) in unscored_slots
        for series, category, unit in expected
    ):
        raise ValueError("图表的明示值范围和不评分范围重叠")
    status = observed.get("table_status")
    if status is None:
        return None
    if status not in {"parsed", "missing", "unparseable"}:
        raise ValueError(f"未知表格交付状态：{status}")
    points = observed.get("values")
    if status == "parsed" and points is None:
        return None
    if status != "parsed" and points:
        raise ValueError("未交付可解析表格，不能提供已解析的数据项")
    return _chart_column_values(expected, unscored_slots, observed) | {"table_status": status}


def _protection(observed: dict) -> str:
    on_state, off_state = observed.get("on_state"), observed.get("off_state")
    if on_state is None or off_state is None:
        return "evidence_missing"
    if on_state not in PROTECTION_STATES or off_state not in PROTECTION_STATES:
        raise ValueError("保护状态应为 complete、partial 或 missing")
    if on_state == off_state == "complete":
        return "intact"
    if "complete" in (on_state, off_state):
        return "deletion_on" if off_state == "complete" else "deletion_off"
    return "baseline_incomplete"


def _check_attribution(case: dict, observed: dict, owners: set) -> None:
    keys = ("fields", "relations") if case["feature"] == "image" else ("values",)
    evidence_ids = [(key, row["id"]) for key in keys for row in observed.get(key) or []]
    if case["feature"] == "image" and observed.get("sub_type") is not None:
        evidence_ids.append(("subtype", observed.get("subtype_id")))
    for kind, evidence_id in evidence_ids:
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError(f"{kind} 证据需要实际输出 ID")
        key = (case["document_id"], case["feature"], kind, evidence_id)
        if key in owners:
            raise ValueError(f"同一 {kind} 证据不能重复归属：{evidence_id}")
        owners.add(key)


def _validate_case(case: dict) -> None:
    document = case["document_id"]
    page = case["page"]
    feature = case["feature"]
    if not isinstance(document, str) or not document.strip():
        raise ValueError("需要稳定、非空的 document_id")
    if type(page) is not int or page < 1 or feature not in FEATURES:
        raise ValueError("需要从 1 开始的物理页码和有效的专项名")
    protected = case.get("protected", False)
    if type(protected) is not bool:
        raise ValueError("protected 须是布尔值")
    if protected or feature in {"image", "chart"}:
        if not _text(case["source_id"]):
            raise ValueError("需要 GT 来源 ID")
    if protected:
        return
    if feature == "header_footer":
        for block in case["blocks"]:
            kind = block["type"]
            if kind not in EDGE_TYPES or (
                not kind.endswith("_image") and not _text(block.get("text", ""))
            ):
                raise ValueError(f"无效的页眉页脚 GT：{block}")
    if feature == "image":
        kind = case["sub_type"]
        if kind == "other":
            return
        if kind not in IMAGE_GROUPS:
            raise ValueError(f"未纳入本轮图片主分的 subtype：{kind}")
        if kind != "natural_image" and not case["fields"]:
            raise ValueError("无可核字段的非照片样本不进入图片主分")
        if kind != "flowchart" and "relations" in case:
            raise ValueError("只有已复核的流程图可以计关系分")
        nodes = _index(case["fields"], key="key")
        if any(
            not set(_relation(relation)) <= nodes.keys() for relation in case.get("relations", [])
        ):
            raise ValueError("GT 连线端点必须引用已标注节点")


def _summaries(rows: dict) -> dict:
    summaries = {}
    for feature in FEATURES:
        planned = [
            row
            for row in rows.values()
            if row["feature"] == feature
            and not row["protected"]
            and row["status"] != "diagnostic_only"
        ]
        scored = [row for row in planned if row["status"] == "scored"]
        summary = {
            "score": None,
            "planned": len(planned),
            "scored": len(scored),
            "coverage": _coverage(len(planned), len(scored)),
            "score_status": "not_covered" if not planned else "pending_evidence",
            "pending_cases": [
                key
                for key, row in rows.items()
                if (
                    row["feature"] == feature
                    and not row["protected"]
                    and row["status"] not in {"scored", "diagnostic_only"}
                )
            ],
        }
        summaries[feature] = summary
        if feature == "image":
            strata = defaultdict(list)
            for row in planned:
                strata[row["stratum"]].append(row["score"])
            stratum_scores = {
                key: mean(values) if values and None not in values else None
                for key, values in strata.items()
            }
            photo_scores = [
                stratum_scores.get(key) for key in ("photo_with_text", "photo_without_text")
            ]
            stratum_scores["natural_image"] = (
                mean(photo_scores) if None not in photo_scores else None
            )
            summary["groups"] = {}
            for key in (
                "text_image",
                "flowchart",
                "photo_with_text",
                "photo_without_text",
                "seal",
            ):
                values = strata.get(key, [])
                planned_count = len(values)
                scored_count = sum(value is not None for value in values)
                group_score = stratum_scores.get(key)
                summary["groups"][key] = {
                    "score": group_score,
                    "planned": planned_count,
                    "scored": scored_count,
                    "coverage": _coverage(planned_count, scored_count),
                    "score_status": _score_status(group_score, planned_count, scored_count),
                }
            group_scores = [stratum_scores.get(key) for key in IMAGE_GROUPS]
            if None not in group_scores:
                summary["score"] = mean(group_scores)
            summary["score_status"] = _score_status(
                summary["score"], summary["planned"], summary["scored"]
            )
            summary["score_basis"] = "stratified_macro_mean"
            summary["subtypes"] = _subtype_summary(
                [row for row in rows.values() if row["feature"] == "image" and not row["protected"]]
            )
        elif feature == "appendix":
            documents = defaultdict(list)
            for row in planned:
                documents[row["document_id"]].append(row["score"])
            summary["documents"] = len(documents)
            summary["on_complete_pages"] = sum(row["on_complete"] for row in scored)
            summary["off_residual_pages"] = sum(row["off_residual"] for row in scored)
            if planned and len(planned) == len(scored):
                summary["score"] = mean(mean(scores) for scores in documents.values())
            summary["score_status"] = _score_status(
                summary["score"], summary["planned"], summary["scored"]
            )
            summary["score_basis"] = "document_macro_mean"
        elif feature == "chart":
            hits = sum(row["matched_values"] for row in scored)
            summary.update(
                score_basis="explicit_value_recall",
                matched_values=hits,
                parsed_tables=sum(row["table_status"] == "parsed" for row in scored),
                unmatched_output_cells=sum(row["unmatched_output_cells"] for row in scored),
                header_conflict_cases=[
                    case_id
                    for case_id, row in rows.items()
                    if any(match["header_conflicts"] for match in row.get("column_matches", []))
                ],
            )
            if planned and len(scored) == len(planned):
                summary["score"] = 100 * hits / sum(row["expected_values"] for row in scored)
                summary["score_status"] = "scored"
        elif planned and len(planned) == len(scored):
            summary.update(_micro(scored))
            summary["score_status"] = _score_status(
                summary["score"], summary["planned"], summary["scored"]
            )
            summary["score_basis"] = "micro_f1"
        else:
            summary["score_status"] = _score_status(
                summary["score"], summary["planned"], summary["scored"]
            )
            summary["score_basis"] = "micro_f1"
    return summaries


def _subtype_summary(rows: list[dict]) -> dict:
    confusion = defaultdict(Counter)
    for row in rows:
        result = row.get("subtype")
        if result is not None:
            prediction = result["observed"] or f"<{result['status']}>"
            confusion[result["expected"]][prediction] += 1
    scores = {}
    for kind in IMAGE_GROUPS[:-1]:
        truth = confusion.get(kind, {})
        tp = truth.get(kind, 0)
        fn = sum(truth.values()) - tp - truth.get("<evidence_missing>", 0)
        fp = sum(counts.get(kind, 0) for label, counts in confusion.items() if label != kind)
        scores[kind] = _measure(tp, fp, fn) | {"unobserved": truth.get("<evidence_missing>", 0)}
    return {"confusion": dict(confusion), "by_class": scores}


def score_feature_rubric(gt: dict, evidence: dict) -> dict:
    """Aggregate one version against a frozen set of reviewed cases."""
    if gt.get("schema_version") != GT_SCHEMA:
        raise ValueError(f"需要 {GT_SCHEMA} 格式的计分清单")
    if not isinstance(gt.get("gt_version"), str) or not gt["gt_version"].strip():
        raise ValueError("需要非空的 GT 版本名 gt_version")
    if evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise ValueError(f"需要 {EVIDENCE_SCHEMA} 格式的计分证据")
    split = gt["split"]
    if split not in {"calibration", "evaluation"}:
        raise ValueError("GT split 应为 calibration 或 evaluation")
    stage = evidence["stage"]
    if stage not in {"final", "replay"} or not _text(evidence["model"]):
        raise ValueError("需要真实模型标识及 final/replay 阶段")
    if stage == "final" and evidence.get("relevel_applied") is False:
        raise ValueError("未执行目标标题重排的回放不能声明为 final 成品")
    config = evidence["config"]
    if any(
        type(config.get(key)) is not type(value) or config[key] != value
        for key, value in CONFIG.items()
    ):
        raise ValueError(f"专项配置必须固定为 {CONFIG}")
    expected, observed = _index(gt["cases"]), evidence["cases"]
    if not isinstance(observed, dict):
        raise ValueError("cases 证据必须按 case ID 索引")
    if observed.keys() - expected.keys():
        raise ValueError("证据含不在冻结 GT 清单中的 case")
    rows, scopes, owners = {}, set(), set()
    for case_id, case in expected.items():
        try:
            _validate_case(case)
            observation = observed.get(case_id, {})
            if not isinstance(observation, dict):
                raise ValueError("case 证据必须是对象")
            feature, protected = case["feature"], case.get("protected") is True
            source = case.get("source_id") if protected or feature in {"image", "chart"} else None
            scope = (case["document_id"], case["page"], feature, protected, source)
            if scope in scopes:
                raise ValueError("同一来源单元不可重复纳入分母")
            scopes.add(scope)
            row = {
                "feature": feature,
                "document_id": case["document_id"],
                "page": case["page"],
                "source_id": case.get("source_id"),
                "protected": protected,
                "score": None,
                "status": "evidence_missing",
            }
            if protected:
                row.update(
                    on_state=observation.get("on_state"), off_state=observation.get("off_state")
                )
                row["status"] = (
                    _protection(observation)
                    if _verified_pair(case, evidence.get("captures", {}))
                    else "pair_unverified"
                )
            else:
                if feature in {"appendix", "header_footer"}:
                    scorer = _appendix if feature == "appendix" else _header_footer
                    values = scorer(case, observation)
                    if not _verified_pair(case, evidence.get("captures", {})):
                        values, row["status"] = None, "pair_unverified"
                else:
                    _check_attribution(case, observation, owners)
                    values = (
                        _image(case, observation)
                        if feature == "image"
                        else _chart(case, observation)
                    )
                if values is not None:
                    row.update(values)
                    if values["score"] is not None or feature == "header_footer":
                        row["status"] = "scored"
                if (feature == "chart" and not case["values"]) or (
                    feature == "image" and case["sub_type"] == "other"
                ):
                    row.update(status="diagnostic_only", score=None)
            row["missing_reasons"] = _missing_reasons(case, observation, row["status"])
            rows[case_id] = row
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"case {case_id}：{error}") from error

    features = _summaries(rows)
    for feature, summary in features.items():
        cases = [
            case
            for case in expected.values()
            if case["feature"] == feature
            and not case.get("protected")
            and rows[case["id"]]["status"] != "diagnostic_only"
        ]
        summary["denominator"] = {
            "unit": {
                "appendix": "pages",
                "header_footer": "blocks",
                "image": "source_images_and_seals",
                "chart": "explicit_values",
            }[feature],
            "count": sum(
                len(case["blocks"])
                if feature == "header_footer"
                else len(case["values"])
                if feature == "chart"
                else 1
                for case in cases
            ),
            "case_count": len(cases),
        }
    scores = [metrics["score"] for metrics in features.values()]
    protection = {key: row for key, row in rows.items() if row["protected"]}
    deletions = [key for key, row in protection.items() if row["status"].startswith("deletion_")]
    pending = [
        key
        for key, row in protection.items()
        if row["status"] not in {"intact", "deletion_on", "deletion_off"}
    ]
    absent = sorted(set(FEATURES) - {row["feature"] for row in protection.values()})
    gate = "fail" if deletions else "pending" if pending or absent else "pass"
    formal = stage == "final" and split == "evaluation"
    overall_status = (
        "calibration_only" if not formal else "scored" if None not in scores else "pending_evidence"
    )
    return {
        "model": evidence["model"],
        "rubric_version": RUBRIC_VERSION,
        "stage": stage,
        "split": split,
        "features": features,
        "overall": mean(scores) if formal and None not in scores else None,
        "overall_status": overall_status,
        "overall_blockers": (
            ([f"stage={stage}"] if stage != "final" else [])
            + ([f"split={split}"] if split != "evaluation" else [])
            + [
                f"{name}:{value['score_status']}"
                for name, value in features.items()
                if value["score"] is None
            ]
        ),
        "score_basis": {
            "weights": {feature: 25 for feature in FEATURES},
            "formula": "mean of four feature scores; null blocks overall",
            "null_policy": "missing evidence is pending and is never converted to zero",
        },
        "deletion_gate": {
            "status": gate if formal else "calibration_only",
            "observed_status": gate,
            "confirmed_deletions": deletions,
            "pending": pending,
            "uncovered_features": absent,
        },
        "cases": rows,
    }


def evaluate_feature_rubric(gt_path: Path, evidence_path: Path, output: Path) -> dict:
    gt, evidence = read_json(gt_path), read_json(evidence_path)
    gt_hash = sha256(gt_path)
    if evidence.get("gt_sha256") != gt_hash:
        raise ValueError("计分证据的 GT 哈希与冻结清单不符")
    metrics = score_feature_rubric(gt, evidence)
    rows = metrics.pop("cases")
    output = fresh_directory(output)
    write_json(output / "metrics.json", metrics)
    write_json(output / "per_case.json", rows)
    write_json(
        output / "pending_cases.json",
        {key: row for key, row in rows.items() if row["missing_reasons"]},
    )
    (output / "report.md").write_text(_report(metrics, rows), encoding="utf-8")
    write_json(
        output / "provenance.json",
        {
            "gt_sha256": gt_hash,
            "evidence_sha256": sha256(evidence_path),
            "config": evidence["config"],
            "gt_version": gt["gt_version"],
            "gt_schema": GT_SCHEMA,
            "evidence_schema": EVIDENCE_SCHEMA,
            "rubric_version": RUBRIC_VERSION,
            "scorer_sha256": sha256(Path(__file__)),
            "contract_sha256": sha256(Path(__file__).with_name("feature_contract.py")),
            "relevel_applied": evidence.get("relevel_applied"),
            "stage": evidence["stage"],
            "split": gt["split"],
        },
    )
    return {"output": str(output), **metrics}


def _report(metrics: dict, rows: dict) -> str:
    lines = [
        f"# {metrics['model']} · 四功能专项评分",
        "",
        f"证据阶段 `{metrics['stage']}`，GT split `{metrics['split']}`。分数为 0–100；coverage 仅表示评分证据覆盖，不能当成质量分。",
        "",
        "| 专项 | 分数 | GT 分母 | 可评分 case / 计划 case | 状态 |",
        "| --- | ---: | --- | ---: | --- |",
    ]
    for name, summary in metrics["features"].items():
        denominator = summary["denominator"]
        score = "null" if summary["score"] is None else f"{summary['score']:.2f}"
        lines.append(
            f"| {name} | {score} | {denominator['count']} {denominator['unit']} | "
            f"{summary['scored']} / {summary['planned']} | {summary['score_status']} |"
        )
    chart = metrics["features"]["chart"]
    if chart["planned"]:
        lines.extend(
            [
                "",
                f"图表明示值命中 {chart['matched_values']} / {chart['denominator']['count']}，"
                f"可解析表格 {chart['parsed_tables']} / {chart['planned']}。",
                f"待复核的列名或单位冲突共 {len(chart['header_conflict_cases'])} 张图。",
            ]
        )
        lines.extend(f"- `{case_id}`" for case_id in chart["header_conflict_cases"])
    overall = "null" if metrics["overall"] is None else f"{metrics['overall']:.2f}"
    lines.extend(
        [
            "",
            f"四项等权总分：**{overall}**，状态 `{metrics['overall_status']}`。",
            f"未出总分原因：{', '.join(metrics['overall_blockers']) or '无'}。",
            "",
            f"误删 gate：`{metrics['deletion_gate']['status']}`；当前证据判定 `{metrics['deletion_gate']['observed_status']}`。质量分与误删门槛分别报告。",
            "",
            "| case | 分数 | 内容诊断 | 状态 | 缺少的证据 |",
            "| --- | ---: | ---: | --- | --- |",
        ]
    )
    for case_id, row in rows.items():
        score = "null" if row["score"] is None else f"{row['score']:.2f}"
        content = row.get("content_score")
        diagnostic = "—" if content is None else f"{content:.2f}"
        lines.append(
            f"| {case_id} | {score} | {diagnostic} | {row['status']} | "
            f"{', '.join(row['missing_reasons']) or '—'} |"
        )
    return "\n".join(lines) + "\n"
