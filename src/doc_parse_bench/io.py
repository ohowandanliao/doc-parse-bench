"""Small, explicit filesystem helpers shared by commands."""

import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh_directory(path: Path) -> Path:
    """Never mix artifacts from different datasets or policies."""
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"输出目录非空，请选用新目录：{path}")
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def safe_name(value: str) -> str:
    if not value or value in {".", ".."} or any(c in value for c in "/\\\x00"):
        raise ValueError(f"无效文档名：{value!r}")
    return value
