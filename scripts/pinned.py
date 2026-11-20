"""Packs of the official list whose skills are not copied here but pinned in their author's
GitHub repository: pinned/<pack>/pack.yml names them, and pinned/<pack>/pins.json, written
by `scripts/mirror.py --pin`, holds the commit and the SHA-256 of every file duskcode fetches
(store/upstream.rs). Shared by repo.py (the checks), publish.py (the list entry) and
check-index.py (fetching the pins again).

A problem is a line of text; nothing here stops at the first one."""

import json
import re

import yaml

import repo

FIELDS = {"name", "title", "description", "vendor", "kind", "license", "repo", "commit", "items"}
PINS = {"repo", "commit", "files", "notes"}
FILE = {"path", "to", "sha256", "size"}
PART = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_FILES = 200
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_PATH = 300


def plain_path(path):
    return isinstance(path, str) and 0 < len(path.encode()) <= MAX_PATH and all(
        part not in (".", "..") and PART.match(part) for part in path.split("/"))


def read(folder):
    """pack.yml and pins.json of `folder`, as read; None for one that cannot be read."""
    try:
        pack = yaml.safe_load((folder / "pack.yml").read_text())
    except (OSError, yaml.YAMLError):
        pack = None
    try:
        pins = json.loads((folder / "pins.json").read_text())
    except (OSError, ValueError):
        pins = None
    return pack, pins


def upstream(pins):
    """The `upstream` of the list entry: what duskcode fetches and checks."""
    return {"repo": pins["repo"], "commit": pins["commit"], "files": pins["files"]}


def source(pack):
    return f"https://github.com/{pack['repo']}/tree/{pack['commit']}"


def problems(folder, meta):
    name = folder.name
    pack, pins = read(folder)
    if not isinstance(pack, dict) or set(pack) != FIELDS:
        return [f"{name}: pinned pack.yml holds exactly {' '.join(sorted(FIELDS))}"]
    if not isinstance(pins, dict) or set(pins) != PINS:
        return [f"{name}: no pins.json of {' '.join(sorted(PINS))}; run scripts/mirror.py --pin {name}"]
    found = []
    if pack["name"] != name or not repo.PACK_NAME.match(name):
        found.append(f"{name}: the name is the folder's, of a-z, 0-9 and -")
    if not all(repo.plain(pack[key]) for key in ("title", "description", "vendor")):
        found.append(f"{name}: title, description and vendor are one line of up to {repo.MAX_TEXT} characters")
    if pack["kind"] != "skills":
        found.append(f"{name}: a pinned pack holds skills")
    found += repo.credit_problems(name, pack["vendor"], pack["license"], source(pack))
    if company := repo.company_in(f"{name} {pack['title']}"):
        found.append(f"{name}: the name or title carries the company name {company}; name it in vendor")
    if repo.UNAFFILIATED not in str(pack["description"]).lower():
        found.append(f"{name}: the description of work from an upstream says \"{repo.UNAFFILIATED} <author>\"")
    items = pack["items"]
    if not isinstance(items, dict) or not 1 <= len(items) <= repo.MAX_ITEMS \
            or not all(isinstance(i, str) and repo.PACK_NAME.match(i) and plain_path(p) for i, p in items.items()):
        return found + [f"{name}: items map 1 to {repo.MAX_ITEMS} names of a-z, 0-9 and - to folders of the repository"]
    if pins["repo"] != pack["repo"] or pins["commit"] != pack["commit"]:
        found.append(f"{name}: pins.json is of {pins['repo']}@{pins['commit'][:7]}, pack.yml names "
                     f"{pack['repo']}@{str(pack['commit'])[:7]}; run scripts/mirror.py --pin {name}")
    if not re.match(r"^[0-9a-f]{40}$", str(pack["commit"])) or not re.match(r"^[\w.-]+/[\w.-]+$", str(pack["repo"])):
        found.append(f"{name}: repo is owner/name and commit is 40 hex digits")
    files = pins["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        return found + [f"{name}: one upstream pins 1 to {MAX_FILES} files"]
    paths, targets = set(), set()
    for f in files:
        if not isinstance(f, dict) or set(f) != FILE or not plain_path(f["path"]) or not plain_path(f["to"]) \
                or not re.match(r"^[0-9a-f]{64}$", str(f["sha256"])) \
                or not isinstance(f["size"], int) or not 1 <= f["size"] <= MAX_FILE_BYTES:
            found.append(f"{name}: a pinned file is {{path, to, sha256, size}} with plain paths and a size of 1 to 4 MiB: {f}")
            continue
        if f["path"] in paths or f["to"] in targets:
            found.append(f"{name}: {f['path']} is pinned twice")
        paths.add(f["path"])
        targets.add(f["to"])
        item = f["to"].split("/", 1)[0]
        # A file comes from its item's folder, or is a licence file of the repository's top.
        if item in items and not f["path"].startswith(items[item] + "/") and "/" in f["path"]:
            found.append(f"{name}: {f['to']} is pinned from {f['path']}, outside {items[item]}")
    if {to.split("/", 1)[0] for to in targets} != set(items) \
            or not all(f"{item}/SKILL.md" in targets for item in items):
        found.append(f"{name}: the pins are exactly the items' folders, each with its SKILL.md; "
                     f"run scripts/mirror.py --pin {name}")
    return found + repo.meta_problems(name, meta)
