"""Internal subprocess entry point. Evaluator modules never enter the CLI process."""

import importlib
import json
import os
import sys
import types
from pathlib import Path


def main():
    backend, root, config_path = sys.argv[1:]
    config = json.loads(Path(config_path).read_text())
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    exact_teds = config.pop("exact_teds", False)
    if not config.pop("enable_cdm", False):
        # Avoid importing optional image/TeX renderer dependencies when CDM is off.
        # Fail if the evaluator attempts to invoke the disabled metric.
        name = "src.metrics.cdm_metric" if backend == "OmniDocBench" else "metrics.cdm_metric"
        stub = types.ModuleType(name)

        class DisabledCDM:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("CDM 未启用；使用 --cdm 并安装官方公式渲染依赖")

        stub.CDM = DisabledCDM
        sys.modules[name] = stub
    os.makedirs("result", exist_ok=True)
    if backend == "MPDocBench":
        os.makedirs("result/eval", exist_ok=True)
    if backend == "OmniDocBench":
        from src.core.registry import (
            DATASET_REGISTRY,
            EVAL_TASK_REGISTRY,
            load_default_registrations,
        )

        load_default_registrations()
    else:
        from registry.registry import DATASET_REGISTRY, EVAL_TASK_REGISTRY

        for name in ("dataset", "metrics", "task"):
            importlib.import_module(name)
    if exact_teds:
        from .exact_teds import install, omnidocbench_pair_worker

        name = "src.metrics.table_metric" if backend == "OmniDocBench" else "metrics.table_metric"
        install(importlib.import_module(name))
        if backend == "OmniDocBench":
            importlib.import_module(
                "src.metrics.cal_metric"
            )._teds_pair_worker = omnidocbench_pair_worker
    task_config = config["end2end_eval"]
    dataset = DATASET_REGISTRY.get(task_config["dataset"]["dataset_name"])(task_config)
    EVAL_TASK_REGISTRY.get("end2end_eval")(
        dataset, task_config["metrics"], task_config["dataset"]["ground_truth"]["data_path"], "eval"
    )


if __name__ == "__main__":
    main()
