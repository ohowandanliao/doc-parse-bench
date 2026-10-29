This directory contains the minimal historical scoring code needed to reproduce
the supplied OmniDocBench 1.5 based evaluation pack. The original service,
annotation agents, scripts, examples and detection tasks are not included.

The matching and metric calculations are retained. Dataset/task registrations
are limited to the Markdown compatibility path. Machine-specific import paths
were removed. See LICENSE for the upstream license; table_metric.py retains
its original IBM Apache 2.0 notice.

This is internal project code, not a third submodule. Changes to scoring behavior
require comparison with the historical XLSX baselines.

Optional FormulaCDM uses renderer helpers from the pinned MPDocBench submodule;
it does not claim to reproduce an unavailable historical TeX environment.
