"""Create a non-overwriting SHA-256 inventory for one preserved research artifact tree."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from research.pilot import sha256, write_json


def create(root: Path, output: Path) -> dict[str, object]:
    if output.exists():
        raise ValueError(
            "Checksum manifest exists; preserved inventories are not overwritten"
        )
    root = root.resolve()
    output = output.resolve()
    if not root.is_dir() or root not in output.parents:
        raise ValueError("Output must be a new file inside the artifact tree")
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path == output:
            continue
        files.append(
            {
                "path": str(path.relative_to(root)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path.read_bytes()),
            }
        )
    result: dict[str, object] = {
        "schema_version": 1,
        "status": "VERIFIED",
        "created_at": datetime.now(UTC).isoformat(),
        "artifact_root": str(root),
        "file_count": len(files),
        "files": files,
    }
    write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create(args.root, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
