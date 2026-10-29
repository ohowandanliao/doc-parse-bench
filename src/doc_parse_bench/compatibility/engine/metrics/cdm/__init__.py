"""Use the pinned MPDocBench renderer helpers for optional FormulaCDM.

Historical matching and metric aggregation remain in the compatibility engine.
Only renderer helpers are shared with one of the two official submodules.
"""
from doc_parse_bench.compatibility import PROJECT_ROOT

__path__ = [str(PROJECT_ROOT / "vendor/Qwen-Doc/MPDocBench/metrics/cdm")]
