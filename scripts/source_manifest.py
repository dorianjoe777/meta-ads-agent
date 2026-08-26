#!/usr/bin/env python3
"""Create a deterministic digest of the committed product source.

The digest deliberately follows ``git ls-files`` so generated runtime state,
Docker volumes, release ZIPs, and ignored local files cannot silently become
part of a canary build.  The same digest is used as the Docker image
provenance label and by the canary integrity checker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def tracked_files(root: Path) -> list[str]:
    raw = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z"],
        stderr=subprocess.STDOUT,
    )
    return sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)


def build_manifest(root: Path) -> dict:
    entries: list[dict[str, str | int]] = []
    digest = hashlib.sha256()
    for relative in tracked_files(root):
        path = root / relative
        if not path.is_file():
            raise SystemExit(f"tracked source file is missing: {relative}")
        content = path.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()
        entries.append({"path": relative, "sha256": file_hash, "bytes": len(content)})
        # Include the path and size delimiters so concatenation cannot produce
        # the same digest for two different file trees.
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return {
        "schema": "admira-source-manifest-v1",
        "algorithm": "sha256(path\\0size\\0content\\0)",
        "file_count": len(entries),
        "sha256": digest.hexdigest(),
        "files": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="", help="Git worktree root (default: script parent)")
    parser.add_argument("--json", action="store_true", help="Print the complete manifest")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve() if args.root else Path(__file__).resolve().parent.parent
    manifest = build_manifest(root)
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(manifest["sha256"])


if __name__ == "__main__":
    main()
