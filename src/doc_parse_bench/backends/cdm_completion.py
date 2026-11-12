"""Score saved formula matches with the pinned official CDM implementations.

Only exact repeated renderer inputs are cached, within one backend and code version.
The source matching, predictions, and all previously computed metrics stay frozen.
"""

import argparse
import hashlib
import importlib
import inspect
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from ..compatibility import PROJECT_ROOT
from ..io import read_json, sha256, write_json
from ..metrics import normalize_report_metrics

_METRIC_MODULE = None


def initialize(backend):
    global _METRIC_MODULE
    root = (
        PROJECT_ROOT
        / "vendor"
        / ("OmniDocBench" if backend == "OmniDocBench" else "Qwen-Doc/MPDocBench")
    )
    sys.path.insert(0, str(root))
    prefix = "src.metrics" if backend == "OmniDocBench" else "metrics"
    _METRIC_MODULE = importlib.import_module(prefix + ".cal_metric")
    if backend == "MPDocBench":
        renderer = importlib.import_module("metrics.cdm_metric")
        ransac = renderer.ransac
        if "random_state" not in inspect.signature(ransac).parameters:
            # scikit-image renamed the seed argument; preserve the upstream seed.
            def compatible_ransac(*args, random_state=None, **kwargs):
                return ransac(*args, rng=random_state, **kwargs)

            renderer.ransac = compatible_ransac


def evaluate_case(job):
    case_hash, sample, directory = job
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    previous = Path.cwd()
    try:
        os.chdir(directory)
        # Upstream embeds the temporary path in a filename; keep it relative.
        result = _METRIC_MODULE._process_single_cdm_sample((case_hash, sample, "render", []))
    finally:
        os.chdir(previous)
    if result.get("cdm_error"):
        raise RuntimeError(f"CDM evaluator error for {case_hash}: {result['cdm_error']}")
    score = float(result["cdm_score"])
    if not 0 <= score <= 1:
        raise ValueError(f"Invalid CDM score: {score}")
    write_json(directory / "score.json", {"score": score})
    return case_hash, score


def sample_key(sample):
    # These are all inputs consulted by either upstream sample processor.
    payload = {
        name: sample.get(name) for name in ("gt", "pred", "gt_cdm", "pred_cdm", "pred_cdm_alt")
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def complete_backend(backend, tasks, output, jobs):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    initialize(backend)
    module = Path(_METRIC_MODULE.__file__).resolve()
    renderer = module.parent / "cdm_metric.py"
    fingerprint = hashlib.sha256()
    for path in sorted([module, renderer, *module.parent.glob("cdm/**/*.py")]):
        fingerprint.update(str(path.relative_to(module.parent)).encode())
        fingerprint.update(path.read_bytes())
    fingerprint.update(Path(__file__).read_bytes())
    code_hash = fingerprint.hexdigest()
    cases = {}
    loaded = []
    for task in tasks:
        report = PROJECT_ROOT / task["source_report"]
        matches = list((report / "runtime").rglob("*display_formula_result.json"))
        if len(matches) != 1:
            raise ValueError(f"Expected one saved formula matching file: {report}")
        samples = read_json(matches[0])
        if not samples:
            raise ValueError(f"No saved formula samples: {report}")
        for sample in samples:
            cases.setdefault(sample_key(sample), sample)
        loaded.append((task, report, matches[0], samples))
    cache = output / "cache" / code_hash
    scores = {}
    pending = []
    for case_hash, sample in cases.items():
        directory = cache / case_hash
        if (directory / "score.json").is_file():
            scores[case_hash] = read_json(directory / "score.json")["score"]
        else:
            pending.append((case_hash, sample, str(directory)))
    print(f"{backend}: {len(cases)} unique formula inputs; {len(pending)} pending", flush=True)
    with ProcessPoolExecutor(max_workers=jobs, initializer=initialize, initargs=(backend,)) as pool:
        futures = [pool.submit(evaluate_case, job) for job in pending]
        for future in as_completed(futures):
            case_hash, score = future.result()
            scores[case_hash] = score
            write_json(
                output / "status.json",
                {
                    "backend": backend,
                    "unique_inputs": len(cases),
                    "completed": len(scores),
                },
            )
            print(f"{backend}: CDM {len(scores)}/{len(cases)}", flush=True)
    completed = []
    for task, report, matches, samples in loaded:
        destination = output / "results" / task["model"] / backend
        old_metrics = read_json(report / "metrics.json")
        score = sum(scores[sample_key(sample)] for sample in samples) / len(samples)
        metrics = normalize_report_metrics({**old_metrics, "formula_cdm": score}, backend)
        overall = "omnidocbench_overall" if backend == "OmniDocBench" else "mpdocbench_overall"
        if metrics.get(overall) is None:
            raise ValueError(f"Official Overall is still missing: {task['model']}/{backend}")
        allowed = {"formula_cdm", "omnidocbench_overall", "mpdocbench_overall"}
        for name, value in normalize_report_metrics(old_metrics, backend).items():
            if name not in allowed and metrics.get(name) != value:
                raise ValueError(f"Non-CDM metric changed: {task['model']}/{name}")
        provenance = read_json(report / "provenance.json")
        provenance.update(
            {
                "cdm_enabled": True,
                "complete_official_score": True,
                "completion": {
                    "method": "official-cdm-on-frozen-formula-matches",
                    "source_report": task["source_report"],
                    "source_metrics_sha256": sha256(report / "metrics.json"),
                    "source_provenance_sha256": sha256(report / "provenance.json"),
                    "formula_matches": str(matches.relative_to(PROJECT_ROOT)),
                    "formula_matches_sha256": sha256(matches),
                    "formula_pairs": len(samples),
                    "cdm_code_sha256": code_hash,
                    "adapter": "scikit-image random_state renamed to rng; seed unchanged",
                    "inference_calls": 0,
                    "matching_reruns": 0,
                    "non_cdm_metrics_changed": False,
                },
            }
        )
        per_doc = read_json(report / "per_doc_scores.json")
        grouped = defaultdict(list)
        scored_samples = []
        for sample in samples:
            sample_score = scores[sample_key(sample)]
            scored_samples.append(
                {
                    **sample,
                    "metric": {**sample.get("metric", {}), "CDM": sample_score},
                }
            )
            grouped[Path(sample["img_id"]).stem].append(sample_score)
        for identity, values in grouped.items():
            if identity not in per_doc:
                raise ValueError(f"Formula sample ID absent from original scores: {identity}")
            per_doc[identity] = normalize_report_metrics(
                {
                    **per_doc[identity],
                    "formula_cdm": sum(values) / len(values),
                },
                backend,
            )
        write_json(destination / "metrics.json", metrics)
        write_json(destination / "provenance.json", provenance)
        write_json(destination / "per_doc_scores.json", per_doc)
        write_json(destination / "formula_samples.json", scored_samples)
        (destination / "report.md").write_text(
            f"# {backend} · {task['model']}\n\n"
            f"FormulaCDM: {score:.6f}\n\nOfficial Overall: {metrics[overall]:.6f}\n\n"
            f"Reuses frozen matching and non-CDM scores from `{task['source_report']}`.\n"
        )
        completed.append(
            {
                **task,
                "completed_report": str(destination.relative_to(PROJECT_ROOT)),
                "metrics_sha256": sha256(destination / "metrics.json"),
                "provenance_sha256": sha256(destination / "provenance.json"),
            }
        )
    write_json(output / "completed.json", completed)
    print(f"{backend}: completed {len(completed)} reports", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True, choices=("OmniDocBench", "MPDocBench"))
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    os.environ.setdefault("CDM_SAVE_VIS", "1")
    complete_backend(args.backend, read_json(args.tasks), args.output, args.jobs)


if __name__ == "__main__":
    main()
