"""Lossless-enough intermediate representation; coordinates are normalized xyxy.

Page numbers are one based. Block IDs are unique within a document. Native model
fields and annotation evidence remain in metadata, separate from evaluation fields.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .io import read_json, safe_name, write_json

SCHEMA_VERSION = "doc-parse-bench.v1"
VISUAL_TYPES = {"image", "chart", "seal"}
MARGINAL_TYPES = {"header", "footer", "page_number"}


@dataclass
class Block:
    id: str
    type: str
    text: str = ""
    html: str = ""
    bbox: list[float] | None = None
    level: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Page:
    number: int
    blocks: list[Block] = field(default_factory=list)
    width: float = 1000
    height: float = 1000
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    id: str
    pages: list[Page]
    relations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        safe_name(self.id)
        numbers = [page.number for page in self.pages]
        if numbers != sorted(set(numbers)) or any(n < 1 for n in numbers):
            raise ValueError(f"{self.id}: 页码重复、无序或小于 1")
        ids = [block.id for page in self.pages for block in page.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.id}: block ID 重复")
        for page in self.pages:
            if page.width <= 0 or page.height <= 0:
                raise ValueError(f"{self.id}: 无效页面尺寸")
            for block in page.blocks:
                if block.bbox is not None:
                    x1, y1, x2, y2 = block.bbox
                    if not (0 <= x1 <= x2 <= 1 and 0 <= y1 <= y2 <= 1):
                        raise ValueError(f"{self.id}/{block.id}: 无效 bbox {block.bbox}")
        for relation in self.relations:
            if relation["source"] not in ids or relation["target"] not in ids:
                raise ValueError(f"{self.id}: 关系引用不存在的块 {relation}")

    def dump(self, path: Path) -> None:
        self.validate()
        write_json(path, {"schema_version": SCHEMA_VERSION, **asdict(self)})

    @classmethod
    def load(cls, path: Path) -> "Document":
        obj = read_json(path)
        if obj.pop("schema_version", None) != SCHEMA_VERSION:
            raise ValueError(f"未知中间格式：{path}")
        obj["pages"] = [
            Page(**{**p, "blocks": [Block(**b) for b in p["blocks"]]}) for p in obj["pages"]
        ]
        doc = cls(**obj)
        doc.validate()
        return doc


def load_documents(directory: Path) -> list[Document]:
    docs = [Document.load(path) for path in sorted(directory.glob("*.json"))]
    if not docs:
        raise ValueError(f"没有中间格式文档：{directory}")
    return docs
