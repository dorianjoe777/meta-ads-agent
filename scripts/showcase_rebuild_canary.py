#!/usr/bin/env python3
"""Render the diverse showcase briefs in a disposable Admira canary.

The briefs are authored on the workstation, so their absolute asset paths are
rewritten to the canary's isolated asset directory before rendering.  This
never connects to Meta and never publishes or spends.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")
from motion_graphics import generate_motion_graphic_video  # noqa: E402


ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/app/output/showcase-rebuild")
ASSETS = ROOT / "assets"
results = []
PROGRESS = ROOT / "canary-progress.log"


def progress(message: str) -> None:
    with PROGRESS.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")
    print(message, flush=True)


progress(json.dumps({"canary_root": str(ROOT), "briefs": [path.name for path in sorted(ROOT.glob("*.json"))]}, ensure_ascii=False))


def remap(value: str) -> str:
    if not value:
        return value
    return str(ASSETS / Path(value).name)


for brief_path in sorted(ROOT.glob("*.json")):
    if brief_path.name.startswith("._") or brief_path.name in {"manifest.json", "final-results.json", "canary-results.json"}:
        continue
    progress(json.dumps({"starting": brief_path.name}, ensure_ascii=False))
    payload = json.loads(brief_path.read_text(encoding="utf-8"))
    payload["quality"] = "preview"
    payload["asset_paths"] = [remap(path) for path in payload.get("asset_paths", [])]
    for scene in payload.get("scenes", []):
        if scene.get("media_path"):
            scene["media_path"] = remap(scene["media_path"])
        scene["layer_asset_paths"] = [remap(path) for path in scene.get("layer_asset_paths", [])]
    progress(json.dumps({"rendering": brief_path.name}, ensure_ascii=False))
    try:
        result = generate_motion_graphic_video(payload)
    except BaseException as exc:
        progress(json.dumps({"exception": brief_path.name, "type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False))
        raise
    row = {"slug": brief_path.stem, "ok": bool(result.get("ok")), "result": result}
    results.append(row)
    progress(json.dumps(row, ensure_ascii=False))
    if not result.get("ok"):
        (ROOT / "canary-results.json").write_text(json.dumps({"ok": False, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(1)

(ROOT / "canary-results.json").write_text(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
progress(json.dumps({"ok": True, "count": len(results)}, ensure_ascii=False))
