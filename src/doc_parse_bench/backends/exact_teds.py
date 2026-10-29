"""Exact ordered tree edit distance for large TEDS tables.

The upstream HTML parser, tree builder and rename costs are reused. Only the
distance solver changes: compiled Zhang–Shasha dynamic programming replaces the
Python APTED solver. Insert/delete costs remain one; no pruning or approximation.
"""

import importlib
from functools import lru_cache

import numpy as np
from lxml import etree, html
from numba import njit


@njit(cache=True)
def _distance(leftmost_a, leftmost_b, roots_a, roots_b, labels_a, labels_b, costs):
    n, m = len(leftmost_a) - 1, len(leftmost_b) - 1
    tree = np.zeros((n + 1, m + 1), dtype=np.float64)
    forest = np.zeros((n + 1, m + 1), dtype=np.float64)
    for root_a in roots_a:
        first_a = leftmost_a[root_a]
        for root_b in roots_b:
            first_b = leftmost_b[root_b]
            forest[first_a - 1, first_b - 1] = 0.0
            for i in range(first_a, root_a + 1):
                forest[i, first_b - 1] = forest[i - 1, first_b - 1] + 1.0
            for j in range(first_b, root_b + 1):
                forest[first_a - 1, j] = forest[first_a - 1, j - 1] + 1.0
            for i in range(first_a, root_a + 1):
                for j in range(first_b, root_b + 1):
                    deletion = forest[i - 1, j] + 1.0
                    insertion = forest[i, j - 1] + 1.0
                    if leftmost_a[i] == first_a and leftmost_b[j] == first_b:
                        substitution = forest[i - 1, j - 1] + costs[labels_a[i], labels_b[j]]
                        forest[i, j] = min(deletion, insertion, substitution)
                        tree[i, j] = forest[i, j]
                    else:
                        substitution = forest[leftmost_a[i] - 1, leftmost_b[j] - 1] + tree[i, j]
                        forest[i, j] = min(deletion, insertion, substitution)
    return tree[n, m]


def _index(root):
    nodes, leftmost = [None], [0]

    def visit(node):
        children = [visit(child) for child in node.children]
        index = len(nodes)
        nodes.append(node)
        leftmost.append(leftmost[children[0]] if children else index)
        return index

    visit(root)
    latest = {leftmost[i]: i for i in range(1, len(nodes))}
    return nodes, np.asarray(leftmost), np.asarray(sorted(latest.values()))


def _labels(nodes):
    unique, ids, labels = [], {}, [0]
    for node in nodes[1:]:
        key = (node.tag, node.colspan, node.rowspan, tuple(node.content or ()))
        if key not in ids:
            ids[key] = len(unique)
            unique.append(node)
        labels.append(ids[key])
    return unique, np.asarray(labels)


def exact_score(evaluator, pred, reference, config_class):
    if not pred or not reference:
        return 0.0
    parser = html.HTMLParser(remove_comments=True, encoding="utf-8")
    a, b = html.fromstring(pred, parser=parser), html.fromstring(reference, parser=parser)
    if not a.xpath("body/table") or not b.xpath("body/table"):
        return 0.0
    a, b = a.xpath("body/table")[0], b.xpath("body/table")[0]
    if evaluator.ignore_nodes:
        etree.strip_tags(a, *evaluator.ignore_nodes)
        etree.strip_tags(b, *evaluator.ignore_nodes)
    denominator = max(len(a.xpath(".//*")), len(b.xpath(".//*")))
    nodes_a, left_a, roots_a = _index(evaluator.load_html_tree(a))
    nodes_b, left_b, roots_b = _index(evaluator.load_html_tree(b))
    unique_a, ids_a = _labels(nodes_a)
    unique_b, ids_b = _labels(nodes_b)
    costs = np.empty((len(unique_a), len(unique_b)), dtype=np.float64)
    config = config_class()
    for i, node_a in enumerate(unique_a):
        for j, node_b in enumerate(unique_b):
            costs[i, j] = config.rename(node_a, node_b)
    distance = _distance(left_a, left_b, roots_a, roots_b, ids_a, ids_b, costs)
    return 1.0 - float(distance) / denominator


def install(module, threshold: int = 300):
    """Install a process-local adapter without changing the upstream checkout."""
    original = module.TEDS.evaluate

    @lru_cache(maxsize=256)
    def calculate(pred, reference, structure_only, ignore_nodes):
        evaluator = module.TEDS(structure_only=structure_only, ignore_nodes=ignore_nodes)
        return exact_score(evaluator, pred, reference, module.CustomConfig)

    def evaluate(self, pred, reference):
        if not pred or not reference:
            return original(self, pred, reference)
        if pred.count("<td") + reference.count("<td") < threshold:
            return original(self, pred, reference)
        return calculate(pred, reference, self.structure_only, tuple(self.ignore_nodes or ()))

    module.TEDS.evaluate = evaluate


def omnidocbench_pair_worker(pred, reference, result_queue):
    """Retain upstream timeout isolation under multiprocessing's spawn start method."""
    try:
        module = importlib.import_module("src.metrics.table_metric")
        install(module)
        score = module.TEDS(structure_only=False).evaluate(pred, reference)
        structure = module.TEDS(structure_only=True).evaluate(pred, reference)
        result_queue.put(("success", (score, structure)))
    except Exception as error:
        result_queue.put(("error", f"{type(error).__name__}: {error}"))
