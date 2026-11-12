"""Adapt native MinerU content lists and structured pages without losing annotations."""

from html import escape


def expand_block(raw: dict) -> list[dict]:
    """Recover nested captions and bodies from the 3.x/4.x export contracts."""
    body = dict(raw)
    kind = body.get("type", "text")
    if not body.get("content"):
        body["content"] = (
            body.get("text")
            or body.get("table_body")
            or body.get("code_body")
            or "\n".join(body.get("list_items", []))
        )
    if kind in {"image", "chart"} and body.get("content"):
        # Structured content excludes the image/details wrapper. Restore it before
        # either preprocessing preset runs, following MinerU's Markdown contract.
        summary = escape(str(body.get("sub_type", kind)))
        body["visual_details"] = (
            f"<details>\n<summary>{summary}</summary>\n\n{body['content']}\n</details>"
        )
    before, after = [], []
    for suffix, generic in (("caption", "captions"), ("footnote", "footnotes")):
        values = body.get(generic, body.get(f"{kind}_{suffix}", []))
        for value in values:
            item = value if isinstance(value, dict) else {"content": value}
            if not item.get("content"):
                continue
            annotation = {
                **item,
                "type": f"{'table' if kind == 'table' else 'image'}_{suffix}",
                "native_annotation_of": kind,
            }
            above = suffix == "caption" and kind == "table"
            if item.get("bbox") and body.get("bbox"):
                above = item["bbox"][1] < body["bbox"][1]
            (before if above else after).append(annotation)
    return [*before, body, *after]


def attach_continuations(doc) -> None:
    """Use explicit continues_prev links only; never infer links from GT."""
    previous = {}
    for page in doc.pages:
        for block in page.blocks:
            if block.type == "title":
                previous.pop("text", None)
            if block.type not in {"text", "table"}:
                continue
            prior = previous.get(block.type)
            if block.metadata.get("continues_prev") and prior:
                number, source = prior
                if page.number - number <= 1 and (
                    block.type != "table" or page.number == number + 1
                ):
                    doc.relations.append(
                        {
                            "type": "truncated",
                            "source": source.id,
                            "target": block.id,
                            "method": "native_continues_prev",
                        }
                    )
            previous[block.type] = (page.number, block)
