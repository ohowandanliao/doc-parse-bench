import importlib.util
import random
from pathlib import Path

import pytest

pytest.importorskip("numba")

from doc_parse_bench.backends.exact_teds import exact_score


def test_exact_solver_matches_upstream_with_spans_nested_content_and_empty_cells():
    path = Path(__file__).parents[1] / "vendor/Qwen-Doc/MPDocBench/metrics/table_metric.py"
    if not path.exists():
        pytest.skip("MPDocBench 子模块未检出")
    spec = importlib.util.spec_from_file_location("reference_table_metric", path)
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    rng = random.Random(42)

    def table():
        rows = []
        for _ in range(rng.randint(1, 5)):
            cells = []
            for _ in range(rng.randint(1, 4)):
                span = rng.choice(["", ' colspan="2"', ' rowspan="2"'])
                value = rng.choice(["你好", "12", "", "<b>x</b>", "abc"])
                cells.append(f"<td{span}>{value}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return "<html><body><table>" + "".join(rows) + "</table></body></html>"

    for _ in range(30):
        pred, gt = table(), table()
        for structure_only in (False, True):
            evaluator = upstream.TEDS(structure_only=structure_only)
            assert exact_score(evaluator, pred, gt, upstream.CustomConfig) == pytest.approx(
                evaluator.evaluate(pred, gt), abs=1e-12
            )
