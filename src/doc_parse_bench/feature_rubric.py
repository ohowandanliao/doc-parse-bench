"""Score source-aligned, reviewed evidence for the legacy 129 feature evaluation."""

import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean

from .feature_contract import FEATURE_GT_VERSION, FEATURES, PAIRS
from .io import fresh_directory, read_json, sha256, write_json

GT_SCHEMA = "doc-parse-bench.feature-rubric-gt.v1"
EVIDENCE_SCHEMA = "doc-parse-bench.feature-rubric-evidence.v1"
RUBRIC_VERSION = "legacy129-content-v1"
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


def _number(point: dict, *, truth: bool = False) -> Decimal | str:
    value = point["value"]
    if not isinstance(value, str):
        raise ValueError("图表数值须以字符串提供")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if _text(point["unit"]) == "%" and normalized.endswith("%"):
        normalized = normalized[:-1].rstrip()
    if DECIMAL_VALUE.fullmatch(normalized):
        try:
            return Decimal(normalized)
        except InvalidOperation:
            pass
    if truth:
        raise ValueError(f"明示值 GT 不是有限十进制数：{value!r}")
    return normalized


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


def _chart(case: dict, observed: dict) -> dict | None:
    expected = {_chart_slot(point): _number(point, truth=True) for point in case["values"]}
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

    def unscored(slot: tuple[str, str, str]) -> bool:
        series, category, unit = slot
        return (series, unit, None) in unscored_slots or (series, unit, category) in unscored_slots

    if any(unscored(slot) for slot in expected):
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
    submitted = [(_chart_slot(point), _number(point)) for point in points or []]
    scored = [(slot, number) for slot, number in submitted if not unscored(slot)]
    return _counts(expected.items(), scored) | {
        "table_status": status,
        "unscored_predictions": len(submitted) - len(scored),
    }


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
    if not re.fullmatch(r"bc_[0-9]{3}", document) or not 1 <= int(document[3:]) <= 129:
        raise ValueError(f"不属于 legacy-129 的文档：{document}")
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
    """Aggregate one version against a frozen set of reviewed legacy-129 cases."""
    if gt.get("schema_version") != GT_SCHEMA or gt.get("gt_version") != FEATURE_GT_VERSION:
        raise ValueError(f"需要 {FEATURE_GT_VERSION} 的人工复核计分清单")
    if evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise ValueError("不是 129 专项计分证据")
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
        f"# {metrics['model']} · legacy 129 专项评分",
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
