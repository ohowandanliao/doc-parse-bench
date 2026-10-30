"""Reproducible content fingerprints and conversion-code identity."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .io import sha256


def fingerprint(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def conversion_provenance() -> dict:
    package = Path(__file__).parent
    source = {str(p.relative_to(package)): sha256(p) for p in sorted(package.rglob("*.py"))}
    result = {
        "tool_version": __version__,
        "source_sha256": fingerprint(source),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": None,
        "git_dirty": None,
    }
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=package,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=package,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if commit.returncode == 0:
            result["git_commit"] = commit.stdout.strip()
        if status.returncode == 0:
            result["git_dirty"] = bool(status.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return result
