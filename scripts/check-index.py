#!/usr/bin/env python3
"""Checks an index.json against the rules duskcode's reader applies to format 2
(projects/core/src/plugins/store/index.rs): known fields only, words, dates, https,
sizes, and that each cover and screenshot is the file the list names and the picture its
name says. This is the official list, so it carries no `stars`: duskcode drops an official
or verified listing's stars, since the only count there was a repository's, not the item's.

    scripts/check-index.py /path/to/index.json
"""

import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime

import pictures

ENTRY = {"name", "version", "kind", "description", "platforms", "clients", "permissions", "homepage",
         "providers", "downloads", "category", "tags", "cover", "screenshots", "stars", "created", "updated", "skills"}
DOWNLOAD = {"os", "arch", "url", "sha256", "size"}
WORD = re.compile(r"^[a-z0-9-]{1,32}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SHA = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"plugin", "skill", "pack", "agent"}


def fail(entry, message):
    sys.exit(f"{entry}: {message}")


def check_picture(n, index, item, fields, limit):
    """A cover or screenshot: its fields, and the file beside the list is the one named."""
    if not isinstance(item, dict) or set(item) - fields or not {"path", "sha256", "size"} <= set(item) \
            or not SHA.match(item["sha256"]) or not isinstance(item["size"], int) or not 1 <= item["size"] <= limit:
        fail(n, f"bad picture {item}")
    if not pictures.plain_path(item["path"]):
        fail(n, f"{item['path']}: not a plain relative path")
    data = (index.parent / item["path"]).read_bytes()
    if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        fail(n, f"{item['path']} differs from the list")
    if why := pictures.problem(item["path"], data, limit):
        fail(n, f"{item['path']}: {why}")


def check(path):
    index = json.loads(path.read_text())
    assert set(index) <= {"format", "serial", "expires", "plugins", "verified"}, "unknown top field"
    assert index["format"] == 2 and isinstance(index["serial"], int)
    datetime.fromisoformat(index["expires"].replace("Z", "+00:00"))
    seen = set()
    for e in index["plugins"]:
        n = e.get("name", "?")
        if set(e) - ENTRY:
            fail(n, f"unknown fields {sorted(set(e) - ENTRY)}")
        if "stars" in e:
            fail(n, "the official list carries no stars")
        if not NAME.match(n) or n in seen:
            fail(n, "bad or repeated name")
        seen.add(n)
        if e.get("kind", "plugin") not in KINDS:
            fail(n, "unknown kind")
        if not e["version"] or len(e["version"]) > 40:
            fail(n, "bad version")
        if not e["downloads"]:
            fail(n, "no downloads")
        for d in e["downloads"]:
            if set(d) - DOWNLOAD or not d["url"].startswith("https://") or not SHA.match(d["sha256"]) \
                    or not 1 <= d["size"] <= 64 * 1024 * 1024:
                fail(n, f"bad download {d}")
        if e.get("category") and not WORD.match(e["category"]):
            fail(n, "bad category")
        if len(e.get("tags", [])) > 8 or not all(WORD.match(t) for t in e.get("tags", [])):
            fail(n, "bad tags")
        for key in ("created", "updated"):
            datetime.fromisoformat(e[key].replace("Z", "+00:00"))
        if e.get("skills") and e["kind"] != "pack":
            fail(n, "only a pack names skills")
        if e.get("cover"):
            check_picture(n, path, e["cover"], {"path", "sha256", "size"}, pictures.COVER_LIMIT)
        shots = e.get("screenshots", [])
        if not isinstance(shots, list) or len(shots) > pictures.MAX_SCREENSHOTS:
            fail(n, f"screenshots is not a list of at most {pictures.MAX_SCREENSHOTS}")
        for shot in shots:
            check_picture(n, path, shot, {"path", "sha256", "size", "caption"}, pictures.SCREENSHOT_LIMIT)
            if "caption" in shot and not pictures.caption_ok(shot["caption"]):
                fail(n, f"bad caption {shot['caption']!r}")
        if e["kind"] == "pack":
            assert all(NAME.match(s) for s in e["skills"]), n
    for m in index["verified"]:
        assert set(m) == {"name", "url", "key"} and m["url"].startswith("https://")
    print(f"ok: {len(index['plugins'])} entries, serial {index['serial']}")


if __name__ == "__main__":
    check(pathlib.Path(sys.argv[1]))
