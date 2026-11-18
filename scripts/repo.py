"""The rules a Workshop repository must meet before its list is built: this one, or any
repository laid out the same way (docs/external-repositories.md). Shared by publish.py
and check-index.py; the size caps are the ones duskcode's reader applies
(projects/core/src/plugins/store/{pack,content,unpack}.rs).

A problem is a line of text; nothing here stops at the first one."""

import pathlib
import re
import stat

import yaml

import pictures

# The fixed list an item's `categories` are picked from.
CATEGORIES = ("coding", "review", "testing", "security", "research", "writing", "data", "devops",
              "design", "productivity", "devices", "communication")
MAX_CATEGORIES = 3
MAX_TAGS = 8
# Who the Official badge is for: the owner of the official Workshop. Anybody else's work
# is Verified there, and a list of another repository never earns either by saying so.
OWNERS = ("duskcode", "DroBov1Tya")
# Licenses that let the text be copied here with attribution.
LICENSES = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "MPL-2.0",
            "CC-BY-4.0", "CC0-1.0", "Unlicense")
# Company names an item's name and title never carry: the item is not theirs to brand,
# whoever wrote it. The author field is where a company is named.
COMPANIES = ("anthropic", "openai", "nvidia", "microsoft", "google", "amazon", "apple", "meta")
UNAFFILIATED = "not affiliated with or endorsed by"

WORD = re.compile(r"^[a-z0-9-]{1,32}$")
PACK_NAME = re.compile(r"^[a-z0-9-]{1,64}$")
PLUGIN_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PACK_FIELDS = {"name", "title", "description", "vendor", "kind", "items", "license"}
ITEM_FILE = {"skills": "SKILL.md", "agents": "AGENT.md"}
MAX_TEXT = 1024
MAX_ITEMS = 256
MAX_FILES = 4000
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_PACK_BYTES = 256 * 1024 * 1024
MAX_PATH = 300


def badge(author, upstream=None):
    """Official for the owner's own work, Verified for work that came from anybody else."""
    return "official" if author in OWNERS and not upstream else "verified"


def license_ok(text):
    """An SPDX expression of the licenses above joined by AND or OR."""
    parts = text.split() if isinstance(text, str) else []
    return bool(parts) and len(parts) % 2 == 1 and all(p in LICENSES for p in parts[::2]) \
        and all(p in ("AND", "OR") for p in parts[1::2])


def plain(text, limit=MAX_TEXT):
    return isinstance(text, str) and 0 < len(text) <= limit and not any(ord(c) < 0x20 or ord(c) == 0x7F for c in text)


def https(text):
    return plain(text, 200) and text.startswith("https://") and " " not in text


def company_in(text):
    words = set(re.split(r"[^a-z0-9]+", text.lower()))
    return next((c for c in COMPANIES if c in words), None)


def meta_problems(name, meta):
    """The categories and tags of one catalog.yml entry."""
    found = []
    categories = meta.get("categories")
    if not isinstance(categories, list) or not 1 <= len(categories) <= MAX_CATEGORIES \
            or len(set(categories)) != len(categories) or not all(c in CATEGORIES for c in categories):
        found.append(f"{name}: categories are 1 to {MAX_CATEGORIES} of {' '.join(CATEGORIES)}")
    tags = meta.get("tags", [])
    if not isinstance(tags, list) or len(tags) > MAX_TAGS or not all(isinstance(t, str) and WORD.match(t) for t in tags):
        found.append(f"{name}: tags are up to {MAX_TAGS} words of a-z, 0-9 and -")
    return found


def credit_problems(name, author, license, source):
    found = []
    if not plain(author, 64):
        found.append(f"{name}: no author")
    if not license_ok(license):
        found.append(f"{name}: the license is not an SPDX expression of {', '.join(LICENSES)}")
    if not https(source):
        found.append(f"{name}: the source is not an https address")
    return found


def front_matter(file):
    text = file.read_text(errors="replace")
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        return None
    try:
        front = yaml.safe_load(text[4:text.index("\n---", 4)])
    except yaml.YAMLError:
        return None
    return front if isinstance(front, dict) else None


def files_problems(folder):
    """Plain text files only, within the caps the reader unpacks."""
    found, count, total = [], 0, 0
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder.parent.parent)
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            found.append(f"{rel}: not a plain file (links are refused)")
            continue
        count += 1
        total += path.stat().st_size
        if len(str(path.relative_to(folder))) > MAX_PATH:
            found.append(f"{rel}: the path is over {MAX_PATH} bytes")
        if path.stat().st_size > MAX_FILE_BYTES:
            found.append(f"{rel}: over {MAX_FILE_BYTES} bytes")
        elif mode & 0o111:
            found.append(f"{rel}: executable; a pack holds no programs")
        elif b"\0" in path.read_bytes()[:8192]:
            found.append(f"{rel}: a binary file; a pack is text")
    if count > MAX_FILES or total > MAX_PACK_BYTES:
        found.append(f"{folder.name}: {count} files, {total} bytes; at most {MAX_FILES} files and {MAX_PACK_BYTES} bytes")
    return found


def pack_problems(folder, meta):
    name = folder.name
    try:
        pack = yaml.safe_load((folder / "pack.yml").read_text())
    except (OSError, yaml.YAMLError) as error:
        return [f"{name}: pack.yml cannot be read: {error}"]
    if not isinstance(pack, dict) or not PACK_FIELDS <= set(pack) or set(pack) - PACK_FIELDS - {"upstream"}:
        return [f"{name}: pack.yml holds {' '.join(sorted(PACK_FIELDS))} and optionally upstream, nothing else"]
    found = []
    if pack["name"] != name or not PACK_NAME.match(name):
        found.append(f"{name}: the name is the folder's, of a-z, 0-9 and -")
    if not all(plain(pack[key]) for key in ("title", "description", "vendor")):
        found.append(f"{name}: title, description and vendor are one line of up to {MAX_TEXT} characters")
    upstream = pack.get("upstream")
    found += credit_problems(name, pack["vendor"], pack["license"], upstream or "https://own.work")
    if company := company_in(f"{name} {pack['title']}"):
        found.append(f"{name}: the name or title carries the company name {company}; name it in vendor")
    file = ITEM_FILE.get(pack["kind"])
    items = pack["items"]
    if not file or not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS \
            or not all(isinstance(i, str) and PACK_NAME.match(i) for i in items):
        return found + [f"{name}: kind is skills or agents, with 1 to {MAX_ITEMS} items of a-z, 0-9 and -"]
    here = {p.name for p in folder.iterdir() if p.name not in ("pack.yml", ".DS_Store")}
    if here != set(items) or len(set(items)) != len(items):
        found.append(f"{name}: items are not exactly the folders beside pack.yml: {sorted(here ^ set(items))}")
    for item in sorted(here & set(items)):
        front = front_matter(folder / item / file) if (folder / item / file).is_file() else None
        if not front or front.get("name") != item or not front.get("description"):
            found.append(f"{name}/{item}: no {file} whose front matter has this name and a description")
        if upstream and not (list((folder / item).glob("LICENSE*")) and (folder / item / "NOTICE.md").is_file()):
            found.append(f"{name}/{item}: work from an upstream keeps its LICENSE* and a NOTICE.md")
    if upstream and UNAFFILIATED not in pack["description"].lower():
        found.append(f"{name}: the description of work from an upstream says \"{UNAFFILIATED} <author>\"")
    return found + files_problems(folder) + meta_problems(name, meta)


def plugin_problems(folder, meta):
    name = folder.name
    try:
        manifest = yaml.safe_load((folder / "plugin.yml").read_text())
    except (OSError, yaml.YAMLError) as error:
        return [f"{name}: plugin.yml cannot be read: {error}"]
    found = []
    if not isinstance(manifest, dict) or manifest.get("name") != name or not PLUGIN_NAME.match(name) \
            or not plain(str(manifest.get("version", "")), 40):
        found.append(f"{name}: plugin.yml has the folder's name and a version")
    if company := company_in(name):
        found.append(f"{name}: the name carries the company name {company}")
    return found + credit_problems(name, meta.get("author"), meta.get("license"), meta.get("source")) \
        + meta_problems(name, meta)


def picture_problems(root, name, meta):
    found = []
    for file in root.glob(f"covers/{name}.*"):
        if why := pictures.problem(f"covers/{file.name}", file.read_bytes(), pictures.COVER_LIMIT):
            found.append(f"covers/{file.name}: {why}")
    shots = meta.get("screenshots") or []
    if not isinstance(shots, list) or len(shots) > pictures.MAX_SCREENSHOTS:
        return found + [f"{name}: at most {pictures.MAX_SCREENSHOTS} screenshots"]
    for shot in shots:
        if not isinstance(shot, dict) or set(shot) - {"file", "caption"} or "/" in shot.get("file", "/"):
            found.append(f"{name}: a screenshot is {{file, caption}} with a plain file name")
            continue
        path = f"screenshots/{name}/{shot['file']}"
        file = root / path
        if not file.is_file() or file.is_symlink():
            found.append(f"{path} is not a file")
        elif why := pictures.problem(path, file.read_bytes(), pictures.SCREENSHOT_LIMIT):
            found.append(f"{path}: {why}")
        if "caption" in shot and not pictures.caption_ok(shot["caption"]):
            found.append(f"{path}: the caption is not one plain line of up to {pictures.MAX_CAPTION} characters")
    return found


def problems(root):
    """Everything wrong with the repository at `root`, and its items as (kind, name, badge)."""
    root = pathlib.Path(root)
    try:
        catalog = yaml.safe_load((root / "catalog.yml").read_text())
    except (OSError, yaml.YAMLError) as error:
        return [f"catalog.yml cannot be read: {error}"], []
    if not isinstance(catalog, dict) or set(catalog) - {"plugins", "packs"}:
        return ["catalog.yml holds plugins and packs, nothing else"], []
    found, items = [], []
    kinds = (("packs", "pack.yml", pack_problems, {"categories", "tags", "screenshots"}),
             ("plugins", "plugin.yml", plugin_problems,
              {"categories", "tags", "screenshots", "author", "license", "source"}))
    for kind, manifest, check, fields in kinds:
        listed = catalog.get(kind) or {}
        folders = {f.parent.name: f.parent for f in root.glob(f"{kind}/*/{manifest}")}
        for name in sorted(set(listed) ^ set(folders)):
            found.append(f"{name}: in catalog.yml or in {kind}/, not in both")
        for name in sorted(set(listed) & set(folders)):
            meta = listed[name]
            if not isinstance(meta, dict) or set(meta) - fields:
                found.append(f"{name}: catalog.yml takes {' '.join(sorted(fields))} for one of the {kind}")
                continue
            found += check(folders[name], meta) + picture_problems(root, name, meta)
            if kind == "packs":
                pack = yaml.safe_load((folders[name] / manifest).read_text())
                mark = badge(pack.get("vendor"), pack.get("upstream")) if isinstance(pack, dict) else "?"
            else:
                mark = badge(meta.get("author"))
            items.append((kind[:-1], name, mark))
    if len({name for _, name, _ in items}) != len(items):
        found.append("a plugin and a pack share a name")
    return found, items
