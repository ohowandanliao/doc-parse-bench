"""Dataset integrity and overlap checks; these do not replace content review."""

import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

from .io import fresh_directory, sha256, write_json
from .schema import load_documents


def audit_quality(
    source: Path, output: Path, legacy_pdfs: Path | None = None, current_pdfs: Path | None = None
) -> dict:
    documents = load_documents(source)
    counts = Counter(documents=len(documents))
    issues = []
    confirmed, unconfirmed = [], []
    for doc in documents:
        doc.validate()
        counts["pages"] += len(doc.pages)
        evidence = defaultdict(set)
        for page in doc.pages:
            for block in page.blocks:
                counts["blocks"] += 1
                counts[block.type] += 1
                if block.bbox and (
                    block.bbox[0] == block.bbox[2] or block.bbox[1] == block.bbox[3]
                ):
                    issues.append(
                        {"document": doc.id, "block": block.id, "issue": "zero_area_bbox"}
                    )
                if block.type in {"text", "title", "formula"} and not block.text.strip():
                    issues.append({"document": doc.id, "block": block.id, "issue": "empty_text"})
                if block.type == "title" and not isinstance(block.level, int):
                    issues.append(
                        {"document": doc.id, "block": block.id, "issue": "missing_title_level"}
                    )
                if block.type == "table":
                    soup = BeautifulSoup(block.html or block.text, "html.parser")
                    if len(soup.find_all("table")) != 1 or not soup.find("tr"):
                        issues.append(
                            {"document": doc.id, "block": block.id, "issue": "invalid_table"}
                        )
                for key in ("cross_page_text", "cross_page_table"):
                    info = block.metadata.get(key, {})
                    for field, reverse in (
                        ("continues_block_id", True),
                        ("continued_by_block_id", False),
                    ):
                        target = info.get(field)
                        if target:
                            pair = (target, block.id) if reverse else (block.id, target)
                            evidence[pair].add(info.get("status", "missing"))
        for relation in doc.relations:
            states = evidence[(relation["source"], relation["target"])]
            item = {"document": doc.id, **relation, "endpoint_statuses": sorted(states)}
            (confirmed if "PASS" in states else unconfirmed).append(item)
    result = {
        "counts": dict(counts),
        "structural_issues": issues,
        "relations_with_pass_evidence": len(confirmed),
        "unconfirmed_relations": unconfirmed,
        "limitations": [
            "Checks structure and recorded evidence, not all text/table numerical accuracy.",
            "PDF overlap detects exact copies and exact normalized text pages, not all near duplicates.",
        ],
    }
    if bool(legacy_pdfs) != bool(current_pdfs):
        raise ValueError("重复检查需要同时给出两份 PDF 目录")
    if legacy_pdfs:
        result["overlap"] = audit_overlap(legacy_pdfs, current_pdfs)
    output = fresh_directory(output)
    write_json(output / "audit.json", result)
    return {
        "documents": len(documents),
        "pages": counts["pages"],
        "blocks": counts["blocks"],
        "structural_issues": len(issues),
        "relations_with_pass_evidence": len(confirmed),
        "unconfirmed_relations": len(unconfirmed),
        "exact_pdf_duplicates": len(result.get("overlap", {}).get("same_pdf", [])),
        "report": str(output / "audit.json"),
    }


def audit_overlap(legacy: Path, current: Path) -> dict:
    import pypdfium2 as pdfium

    files = {"legacy": sorted(legacy.glob("*.pdf")), "current": sorted(current.glob("*.pdf"))}
    hashes, text_pages, page_counts = {}, {}, {}
    for kind, paths in files.items():
        hashes[kind] = defaultdict(list)
        text_pages[kind] = defaultdict(list)
        page_counts[kind] = 0
        for path in paths:
            hashes[kind][sha256(path)].append(path.name)
            with pdfium.PdfDocument(path) as pdf:
                page_counts[kind] += len(pdf)
                for number in range(len(pdf)):
                    page = pdf[number]
                    textpage = page.get_textpage()
                    text = textpage.get_text_range()
                    textpage.close()
                    page.close()
                    text = re.sub(r"\W+", "", text, flags=re.UNICODE).lower()
                    if len(text) > 100:
                        digest = hashlib.sha256(text.encode()).hexdigest()
                        text_pages[kind][digest].append({"document": path.name, "page": number + 1})
    common = hashes["legacy"].keys() & hashes["current"].keys()
    same_pages = text_pages["legacy"].keys() & text_pages["current"].keys()
    return {
        "documents": {key: len(value) for key, value in files.items()},
        "pages": page_counts,
        "same_pdf": [
            {"legacy": hashes["legacy"][h], "current": hashes["current"][h]} for h in sorted(common)
        ],
        "same_normalized_text_page": [
            {"legacy": text_pages["legacy"][h], "current": text_pages["current"][h]}
            for h in sorted(same_pages)
        ],
    }
