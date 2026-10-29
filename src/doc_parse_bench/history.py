"""Compare saved legacy scores directly with the supplied XLSX workbook."""

import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from .io import fresh_directory, read_json, sha256, write_json

NAMESPACE = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
COLUMNS = {
    "文本准确度↑": "text_accuracy",
    "表格准确度↑": "table_accuracy",
    "顺序准确度↑": "reading_order_accuracy",
    "标题准确度↑": "title",
    "TextEdit↓": "text_edit",
    "FormulaCDM↑": "formula_cdm",
    "Table TEDS↑": "table_teds",
    "Table TEDS-S↑": "table_teds_s",
    "Read OrderEdit↓": "reading_order_edit",
}


def workbook_rows(path: Path) -> list[dict]:
    """Read values without Excel or openpyxl; never execute formulas or macros."""
    with ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root.findall("s:si", NAMESPACE)]
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        headers = None
        rows = []
        for row in sheet.findall(".//s:sheetData/s:row", NAMESPACE):
            values = {}
            for cell in row.findall("s:c", NAMESPACE):
                column = re.match(r"[A-Z]+", cell.attrib["r"])[0]
                value = cell.find("s:v", NAMESPACE)
                text = value.text if value is not None else "".join(cell.itertext())
                values[column] = shared[int(text)] if cell.get("t") == "s" else text
            if "运行标签" in values.values():
                headers = values
            elif headers:
                item = {headers[k]: v for k, v in values.items() if k in headers}
                if item.get("运行标签"):
                    rows.append(item)
        return rows


def compare_workbook(
    workbook: Path, run: Path, tag: str, output: Path, tolerance: float = 0.00005
) -> dict:
    selected = [row for row in workbook_rows(workbook) if row["运行标签"] == tag]
    if len(selected) != 1:
        raise ValueError(f"无法唯一定位运行标签：{tag}")
    row = selected[0]
    metrics_path = run / "metrics.json"
    metrics = read_json(metrics_path)
    comparisons = []
    for column, metric in COLUMNS.items():
        expected = float(row[column])
        actual = metrics.get(metric)
        delta = actual - expected if actual is not None else None
        comparisons.append(
            {
                "column": column,
                "metric": metric,
                "expected": expected,
                "actual": actual,
                "delta": delta,
                "status": (
                    "unavailable"
                    if actual is None
                    else "match"
                    if abs(delta) <= tolerance
                    else "mismatch"
                ),
            }
        )
    report = {
        "tag": tag,
        "workbook_sha256": sha256(workbook),
        "metrics_sha256": sha256(metrics_path),
        "tolerance": tolerance,
        "comparisons": comparisons,
    }
    output = fresh_directory(output)
    write_json(output / "comparison.json", report)
    lines = [
        f"# 历史 XLSX 对账：{tag}",
        "",
        f"容差：{tolerance}。",
        "",
        "| 指标 | XLSX | 本次 | 结论 |",
        "| --- | --- | --- | --- |",
    ]
    for item in comparisons:
        actual = f"{item['actual']:.6f}" if item["actual"] is not None else "未计算"
        lines.append(f"| {item['column']} | {item['expected']:.6f} | {actual} | {item['status']} |")
    (output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "matched": sum(c["status"] == "match" for c in comparisons),
        "mismatched": sum(c["status"] == "mismatch" for c in comparisons),
        "unavailable": sum(c["status"] == "unavailable" for c in comparisons),
        "report": str(output / "comparison.md"),
    }
