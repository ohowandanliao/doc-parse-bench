"""Archive two superseded 129 replay directories without losing historical evidence."""

import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts/legacy129-subimage-20261123"
ARCHIVE = ROOT / "archives/legacy129-intermediate-replays-20261124.zip"
NAMES = ("p2t-replay-v2", "p2t-pre-crop")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if ARCHIVE.exists():
        raise ValueError(f"Archive already exists: {ARCHIVE}")
    inventory = []
    for name in NAMES:
        folder = ARTIFACTS / name
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError(f"Expected a local replay directory: {folder}")
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Unexpected symlink: {path}")
            if path.is_file():
                inventory.append(
                    {
                        "path": str(path.relative_to(ARTIFACTS)),
                        "bytes": path.stat().st_size,
                        "sha256": digest(path.read_bytes()),
                    }
                )
    with ZipFile(ARCHIVE, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for row in inventory:
            archive.write(ARTIFACTS / row["path"], row["path"])
        archive.writestr("INVENTORY.json", json.dumps(inventory, ensure_ascii=False, indent=2))
    with ZipFile(ARCHIVE) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC validation failed")
        for row in inventory:
            if digest(archive.read(row["path"])) != row["sha256"]:
                raise ValueError(f"ZIP content differs: {row['path']}")
            if digest((ARTIFACTS / row["path"]).read_bytes()) != row["sha256"]:
                raise ValueError(f"Source changed during archive: {row['path']}")

    # Only these two exact, verified directories are replaced by restore notes.
    for name in NAMES:
        shutil.rmtree(ARTIFACTS / name)
        (ARTIFACTS / name).mkdir()
        (ARTIFACTS / name / "README.md").write_text(
            f"# {name} · 历史中间回放已归档\n\n"
            "全部原文件及 SHA-256 清单保存在 `archives/legacy129-intermediate-replays-20261124.zip`。\n\n"
            "仓库根目录恢复命令：\n\n```sh\n"
            "unzip archives/legacy129-intermediate-replays-20261124.zip "
            "-d artifacts/legacy129-subimage-20261123/\n```\n\n"
            "当前审阅入口为 `../analysis-units-review-20261124/review.html`；"
            "V2 历史成品在 `../p2t-replay-v2-final/`，前置候选在 `../p2t-split-policy/`。\n",
            encoding="utf-8",
        )
    report = {
        "archived": list(NAMES),
        "files": len(inventory),
        "uncompressed_bytes": sum(row["bytes"] for row in inventory),
        "archive": str(ARCHIVE.relative_to(ROOT)),
        "archive_bytes": ARCHIVE.stat().st_size,
        "archive_sha256": digest(ARCHIVE.read_bytes()),
        "verified": "CRC and SHA-256 of every file before removing source directories",
        "preserved_active": [
            "analysis-units-review-20261124",
            "p2t-replay-v2-final",
            "p2t-split-policy",
            "rubric-charts",
            "rubric-switches",
            "model-gap-v2",
            "ft-original-ir",
            "ft-expanded-ir",
            "p2t-replay",
            "p2t-inner-handoff-20261124",
        ],
    }
    (Path(__file__).with_name("artifact-cleanup-20261124.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
