#!/usr/bin/env python3
"""Checks an index.json against the rules duskcode's reader applies to format 2
(projects/core/src/plugins/store/index.rs): known fields only, words, dates, https,
sizes, and that each cover and screenshot is the file the list names and the picture its
name says. This is the official list, so it carries no `stars`: duskcode drops an official
or verified listing's stars, since the only count there was a repository's, not the item's.
A format 3 list also names each item's author, license, source, categories and badge;
the Official badge is refused for an author who is not the Workshop's owner, and a
plugin's `mcp`, `programs` and `skills` must be exactly what its plugin.yml in this
repository brings (scripts/repo.py `brings`), since duskcode refuses the package otherwise.

    scripts/check-index.py /path/to/index.json
    scripts/check-index.py --repo /path/to/repository   its catalog.yml, packs and plugins,
                                                        before a list is built (scripts/repo.py)
    scripts/check-index.py --unsigned /path/to/index.json [--fetch [NAME ...]]

A format 3 skill or pack may name `upstream`, files pinned at a commit of its author's
GitHub repository (store/upstream.rs), instead of `downloads`. `--unsigned` checks a list
for a source without a key (scripts/mirror.py, docs/mirrors.md): format 3, not expired,
only skills and packs pinned upstream, no pictures or stars; a company's name in an item's
name is only a warning there, since the name is its author's. `--fetch` downloads the
pinned files of every entry, or of the entries named, and checks each as duskcode does
before it writes anything: size, SHA-256, UTF-8 text without NUL, and SKILL.md's front
matter as the skill graph reads it.
"""

import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

import yaml

import pictures
import repo

ENTRY = {"name", "version", "kind", "description", "platforms", "clients", "permissions", "homepage",
         "providers", "downloads", "category", "tags", "cover", "screenshots", "stars", "created", "updated", "skills"}
DOWNLOAD = {"os", "arch", "url", "sha256", "size"}
WORD = re.compile(r"^[a-z0-9-]{1,32}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SHA = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"plugin", "skill", "pack", "agent"}
# What format 3 adds to an entry; all of them or none.
CREDIT = {"author", "license", "source", "categories", "badge"}
# What format 3 adds to a plugin: what it runs and adds, checked against its manifest.
BRINGS = {"mcp", "programs"}
ROOT = pathlib.Path(__file__).resolve().parent.parent
UPSTREAM = {"repo", "commit", "files"}
UPSTREAM_FILE = {"path", "to", "sha256", "size"}
PART = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_UPSTREAM_FILES = 200
MAX_UPSTREAM_BYTES = 4 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_INDEX_BYTES = 4 * 1024 * 1024


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


def plain_path(path, limit=300):
    return isinstance(path, str) and 0 < len(path.encode()) <= limit and all(
        part not in (".", "..") and PART.match(part) for part in path.split("/"))


def check_upstream(n, e):
    """store/upstream.rs `Upstream::check`, and the layout content.rs reads: a skill's
    files all under `<name>/` with its SKILL.md; a pack's under its items' folders."""
    up = e["upstream"]
    if e.get("kind") not in ("skill", "pack") or e.get("downloads"):
        fail(n, "only a skill or a pack comes from upstream, and then without packages")
    if not isinstance(up, dict) or set(up) != UPSTREAM:
        fail(n, f"upstream is exactly {sorted(UPSTREAM)}")
    parts = up["repo"].split("/") if isinstance(up["repo"], str) else []
    if len(parts) != 2 or not all(plain_path(p) for p in parts):
        fail(n, "the upstream repository is not owner/name")
    if not isinstance(up["commit"], str) or not re.match(r"^[0-9a-f]{40}$", up["commit"]):
        fail(n, "the upstream commit is not 40 hex digits")
    files = up["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_UPSTREAM_FILES:
        fail(n, f"an upstream names 1 to {MAX_UPSTREAM_FILES} files")
    paths, targets = set(), set()
    for f in files:
        if not isinstance(f, dict) or set(f) != UPSTREAM_FILE:
            fail(n, f"an upstream file is exactly {sorted(UPSTREAM_FILE)}")
        if not plain_path(f["path"]) or not plain_path(f["to"]):
            fail(n, f"{f['path']} -> {f['to']}: not a plain relative path")
        if f["path"] in paths or f["to"] in targets:
            fail(n, f"{f['path']}: named twice")
        paths.add(f["path"])
        targets.add(f["to"])
        if not isinstance(f["sha256"], str) or not SHA.match(f["sha256"]):
            fail(n, f"{f['path']}: the sha256 is not 64 hex digits")
        if not isinstance(f["size"], int) or not 1 <= f["size"] <= MAX_UPSTREAM_BYTES:
            fail(n, f"{f['path']}: the size is not 1 to {MAX_UPSTREAM_BYTES} bytes")
    tops = {to.split("/", 1)[0] for to in targets}
    if e["kind"] == "skill":
        if tops != {n} or f"{n}/SKILL.md" not in targets:
            fail(n, f"an upstream skill's files are all under {n}/, with {n}/SKILL.md")
    else:
        items = e.get("skills") or []
        if tops != set(items) or not all(f"{item}/SKILL.md" in targets for item in items):
            fail(n, "an upstream pack's files are exactly its skills' folders, each with a SKILL.md")


def fetch_upstream(n, e):
    """Every pinned file, fetched from GitHub's raw host and checked as store/upstream.rs
    `assemble` does, and each SKILL.md read as the skill graph reads it."""
    import urllib.request
    import mirror
    up = e["upstream"]
    for f in up["files"]:
        url = f"https://raw.githubusercontent.com/{up['repo']}/{up['commit']}/{f['path']}"
        request = urllib.request.Request(url, headers={"User-Agent": "duskcode-workshop-check"})
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.geturl() != url:
                fail(n, f"{f['path']}: the raw host redirected, and duskcode follows no redirect here")
            data = response.read(f["size"] + 1)
        if len(data) != f["size"] or hashlib.sha256(data).hexdigest() != f["sha256"]:
            fail(n, f"{f['path']} is not the file the list pins")
        try:
            data.decode()
        except UnicodeDecodeError:
            fail(n, f"{f['path']} is not UTF-8 text")
        if b"\0" in data:
            fail(n, f"{f['path']} holds NUL, so it is not text")
        to = f["to"].split("/")
        if len(to) == 2 and to[1] == "SKILL.md":
            try:
                mirror.read_front(data, to[0])
            except mirror.Skip as skip:
                fail(n, f"{f['to']} will not load as a skill: {skip}")
    return len(up["files"])


def check_credit(n, e, unsigned=False):
    """Who made it and how it is filed, and the badge that follows from the author."""
    if not CREDIT <= set(e):
        fail(n, f"a format 3 entry names {sorted(CREDIT)}")
    why = repo.credit_problems(n, e["author"], e["license"], e["source"]) + repo.meta_problems(n, e)
    if why:
        sys.exit(why[0])
    if e["badge"] not in ("official", "verified") or (e["badge"] == "official" and e["author"] not in repo.OWNERS):
        fail(n, f"the badge is verified for an author who is not {' or '.join(repo.OWNERS)}")
    if e["badge"] == "verified" and e.get("kind") == "pack" and repo.UNAFFILIATED not in e["description"].lower():
        fail(n, "the description of somebody else's work says it is not affiliated")
    if company := repo.company_in(n):
        if unsigned:
            print(f"warning: {n}: the name carries the company name {company}", file=sys.stderr)
        else:
            fail(n, f"the name carries the company name {company}")


def check_brings(n, e, root):
    """A plugin's mcp, programs and skills against its plugin.yml in `root`."""
    file = root / "plugins" / n / "plugin.yml"
    if not file.is_file():
        fail(n, f"no {file.relative_to(root)} to check what it brings against")
    want = repo.brings(file.parent, yaml.safe_load(file.read_text()))
    if why := repo.brings_problems(n, want):
        sys.exit(why[0])
    for key in ("mcp", "programs", "skills"):
        if e.get(key, []) != want[key]:
            fail(n, f"the list's {key} {e.get(key, [])} is not what plugin.yml brings: {want[key]}")


def check_repo(root):
    found, items = repo.problems(root)
    for line in found:
        print(line, file=sys.stderr)
    if found:
        sys.exit(f"{len(found)} problems")
    for kind, name, badge in items:
        print(f"{kind:6} {name:28} {badge}")
    print(f"ok: {len(items)} items")


def check(path, root=ROOT, unsigned=False, fetch=None):
    data = path.read_bytes()
    index = json.loads(data)
    assert set(index) <= {"format", "serial", "expires", "plugins", "verified"}, "unknown top field"
    assert index["format"] in (2, 3) and isinstance(index["serial"], int)
    datetime.fromisoformat(index["expires"].replace("Z", "+00:00"))
    if len(index["plugins"]) > MAX_ENTRIES or len(data) > MAX_INDEX_BYTES:
        sys.exit(f"over duskcode's caps: {MAX_ENTRIES} entries, {MAX_INDEX_BYTES} bytes")
    if unsigned:
        if index["format"] != 3 or index.get("verified"):
            sys.exit("a list without a key is format 3 and vouches for no mirrors")
        if datetime.fromisoformat(index["expires"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            sys.exit(f"the list expired on {index['expires']}")
    seen = set()
    fetched = 0
    for e in index["plugins"]:
        n = e.get("name", "?")
        known = ENTRY | CREDIT | BRINGS | {"upstream"} if index["format"] == 3 else ENTRY
        if set(e) - known:
            fail(n, f"unknown fields {sorted(set(e) - known)}")
        if index["format"] == 3:
            check_credit(n, e, unsigned)
        if unsigned and ("upstream" not in e or set(e) & {"cover", "screenshots", "stars"}):
            fail(n, "a list without a key brings only skills and packs pinned upstream, without pictures or stars")
        if "upstream" in e:
            check_upstream(n, e)
            if fetch is not None and (not fetch or n in fetch):
                fetched += fetch_upstream(n, e)
        if "stars" in e:
            fail(n, "the official list carries no stars")
        if not NAME.match(n) or n in seen:
            fail(n, "bad or repeated name")
        seen.add(n)
        if e.get("kind", "plugin") not in KINDS:
            fail(n, "unknown kind")
        if not e["version"] or len(e["version"]) > 40:
            fail(n, "bad version")
        if not e.get("downloads") and "upstream" not in e:
            fail(n, "no downloads")
        for d in e.get("downloads", []):
            if set(d) - DOWNLOAD or not d["url"].startswith("https://") or not SHA.match(d["sha256"]) \
                    or not 1 <= d["size"] <= 64 * 1024 * 1024:
                fail(n, f"bad download {d}")
        if e.get("category") and not WORD.match(e["category"]):
            fail(n, "bad category")
        if len(e.get("tags", [])) > 8 or not all(WORD.match(t) for t in e.get("tags", [])):
            fail(n, "bad tags")
        for key in ("created", "updated"):
            if key in e or not unsigned:
                datetime.fromisoformat(e[key].replace("Z", "+00:00"))
        if e.get("kind", "plugin") != "plugin" and set(e) & BRINGS:
            fail(n, "only a plugin brings mcp or programs")
        if e.get("skills") and e["kind"] != "pack" and not (index["format"] == 3 and e["kind"] == "plugin"):
            fail(n, "only a pack, or a plugin in format 3, names skills")
        if index["format"] == 3 and e["kind"] == "plugin":
            check_brings(n, e, root)
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
    for m in index.get("verified", []):
        assert set(m) == {"name", "url", "key"} and m["url"].startswith("https://")
    if fetch and not set(fetch) <= seen:
        sys.exit(f"not in the list: {' '.join(sorted(set(fetch) - seen))}")
    print(f"ok: {len(index['plugins'])} entries, serial {index['serial']}"
          + (", unsigned" if unsigned else "") + (f", {fetched} pinned files fetched and checked" if fetch is not None else ""))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--repo":
        check_repo(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "--unsigned" and (len(sys.argv) == 3 or sys.argv[3] == "--fetch"):
        check(pathlib.Path(sys.argv[2]), unsigned=True, fetch=sys.argv[4:] if len(sys.argv) > 3 else None)
    elif len(sys.argv) == 2:
        check(pathlib.Path(sys.argv[1]))
    else:
        sys.exit(__doc__)
