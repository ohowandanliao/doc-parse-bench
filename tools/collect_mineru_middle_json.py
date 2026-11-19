#!/usr/bin/env python3
"""Collect raw MinerU ``middle_json`` responses for the feature evaluation.

This is intentionally a standalone tool.  It talks to MinerU's ``/file_parse``
endpoint, not PDF2Text's ``/v1/pdfparse`` endpoint, because the latter only
returns rendered Markdown and page counts.  The resulting JSON files are
one-time experiment inputs and are not part of the benchmark repository.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import mimetypes
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCHEMA = "doc-parse-bench.mineru-middle-json-run.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _endpoint(value: str) -> str:
    value = value.rstrip("/")
    return value if value.endswith("/file_parse") else f"{value}/file_parse"


def _multipart(
    fields: dict[str, str], field_name: str, filename: str, payload: bytes, content_type: str
) -> tuple[bytes, str]:
    boundary = f"----docbench-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    parts.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            ).encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            payload,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(parts), boundary


def _request(
    path: Path,
    *,
    url: str,
    image_analysis: bool,
    backend: str,
    token: str | None,
    timeout: float,
) -> dict:
    fields = {
        "return_middle_json": "true",
        "return_images": "true",
        "image_analysis": "true" if image_analysis else "false",
        "backend": backend,
    }
    body, boundary = _multipart(
        fields,
        "files",
        path.name,
        path.read_bytes(),
        mimetypes.guess_type(path.name)[0] or "application/pdf",
    )
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit user endpoint
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("MinerU response must be a JSON object")
    return payload


def _collect_one(
    path: Path,
    *,
    url: str,
    image_analysis: bool,
    backend: str,
    token: str | None,
    timeout: float,
) -> dict:
    try:
        payload = _request(
            path,
            url=url,
            image_analysis=image_analysis,
            backend=backend,
            token=token,
            timeout=timeout,
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "document": path.stem,
            "filename": path.name,
            "sha256": _sha256(path),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "document": path.stem,
        "filename": path.name,
        "sha256": _sha256(path),
        "ok": True,
        "payload": payload,
    }


def collect(args: argparse.Namespace) -> int:
    source = args.pdf_dir.resolve()
    output = args.output.resolve()
    if not source.is_dir():
        raise ValueError(f"PDF directory does not exist: {source}")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    paths = sorted(source.glob("*.pdf"))
    if not paths:
        raise ValueError(f"No PDF files found in {source}")
    url = _endpoint(args.url)
    results: list[dict] = []
    worker_args = {
        "url": url,
        "image_analysis": args.image_analysis == "true",
        "backend": args.backend,
        "token": args.token,
        "timeout": args.timeout,
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(_collect_one, path, **worker_args) for path in paths]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            result_path = output / f"{result['document']}.json"
            if result["ok"]:
                serialized = json.dumps(result["payload"], ensure_ascii=False, indent=2) + "\n"
                result_path.write_text(serialized, encoding="utf-8")
                result["response_sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                del result["payload"]
            results.append(result)
            state = "ok" if result["ok"] else "failed"
            print(f"[{state}] {result['filename']}", flush=True)
    results.sort(key=lambda item: item["document"])
    manifest = {
        "schema_version": SCHEMA,
        "documents": len(paths),
        "successful": sum(item["ok"] for item in results),
        "failed": sum(not item["ok"] for item in results),
        "endpoint": url,
        "model": args.model,
        "backend": args.backend,
        "image_analysis": args.image_analysis == "true",
        "return_middle_json": True,
        "return_images": True,
        "source_directory": str(source),
        "records": results,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if manifest["failed"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="MinerU base URL or /file_parse URL")
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-analysis", choices=("true", "false"), required=True)
    parser.add_argument("--backend", default="vlm-vllm-async-engine")
    parser.add_argument("--model", default="mineru3")
    parser.add_argument("--token")
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--jobs", type=int, default=1)
    return parser


if __name__ == "__main__":
    try:
        raise SystemExit(collect(build_parser().parse_args()))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
