"""Historical behavior owned by this project, independent of the original evaluation pack."""

from pathlib import Path

from ..io import fresh_directory, sha256, write_json
from .cleaning import CleaningOptions, normalize_markdown

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENGINE_ROOT = Path(__file__).parent / "engine"


def prepare_legacy(
    source: Path, output: Path, options: CleaningOptions = CleaningOptions()
) -> dict:
    files = sorted(source.glob("*.md"))
    if not files:
        raise ValueError(f"没有 Markdown 预测：{source}")
    output = fresh_directory(output)
    audit = {
        "input_format": "markdown",
        "replace_embedded_images": options.replace_embedded_images,
        "expand_chart_details": options.expand_chart_details,
        "documents": len(files),
        "changed": 0,
        "sources": [],
    }
    for path in files:
        raw = path.read_text(encoding="utf-8")
        fixed = normalize_markdown(raw, options)
        (output / path.name).write_text(fixed, encoding="utf-8")
        audit["changed"] += raw != fixed
        audit["sources"].append({"path": str(path), "sha256": sha256(path)})
    write_json(output / "manifest.json", audit)
    return audit


def historical_overall(raw: dict) -> float | None:
    """Preserve the old aggregate, calculated before title was attached."""
    from ..metrics import finite

    fields = [
        ("text_block", "Edit_dist", "ALL_page_avg", True),
        ("table", "TEDS", "all", False),
        ("reading_order", "Edit_dist", "ALL_page_avg", True),
    ]
    scores = []
    for module, metric, key, invert in fields:
        value = finite(raw.get(module, {}).get("all", {}).get(metric, {}).get(key))
        if value is not None:
            scores.append(round(1 - value if invert else value, 4))
    return round(sum(scores) / len(scores), 4) if scores else None
