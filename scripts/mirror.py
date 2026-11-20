#!/usr/bin/env python3
"""Turns an outside skill catalogue into a Dusk list: a format 3 `index.json` whose every
entry is a skill pinned to a commit of its author's GitHub repository, with the SHA-256 of
each file (the `upstream` path of duskcode's store, projects/core/src/plugins/store/
upstream.rs). The list is not signed: a user adds it by its address as a source without a
key, and duskcode shows what it offers as Unverified. See docs/mirrors.md.

    scripts/mirror.py NAME                   one mirror of mirrors.yml
    scripts/mirror.py --all                  every mirror that is not `manual`
    scripts/mirror.py --list                 the mirrors of mirrors.yml
    scripts/mirror.py --pin [PACK ...]       the pins of the official list's pinned packs
      --limit N        the first N items: skill folders (skills-repo), plugins
                       (claude-marketplace) or index entries (hermes-index), after --match
      --offset N       skip the first N items first, to take a long catalogue in slices
      --match PATTERN  only items whose name or identifier matches this regular expression
                       (case is ignored)
      --dry-run        write nothing; print the report
      --out DIR        write into DIR instead of dist/mirrors/NAME
      --refresh        fetch a cached catalogue index again (the Hermes index is kept a day)
      --no-gh          use GitHub's API over https even when `gh` is logged in
      --pin [PACK ...] write pinned/PACK/pins.json (every pack when none is named): the
                       files of the official list's pinned packs, by the same rules
      --bump           with --pin, move each pack to its repository's current commit
      --survey         hermes-index only: count, by hub, the entries that name a GitHub
                       location (and so can be converted), reading only the index

Kinds of mirror:
  skills-repo         a GitHub repository of SKILL.md folders (the Agent Skills standard)
  claude-marketplace  a repository with .claude-plugin/marketplace.json; only the skills/
                      folders of its plugins are taken, never their MCP servers, hooks,
                      commands or agents
  hermes-index        Hermes Agent's skills index: pointers without commits, each resolved
                      to its GitHub repository and pinned to the commit there now

For each skill the converter pins a commit, lists the files, keeps those duskcode installs
(text in UTF-8 without NUL, 1 byte to 4 MiB, plain paths of at most 300 bytes, at most 200)
and leaves binaries out; scripts are kept. It reads SKILL.md's front matter as duskcode's
skill graph does (projects/core/src/catalog/graph.rs) and skips, with a reason, a skill that
would not load or whose licence is not on the allow-list. Claude Code features duskcode does
not have are named in the entry's description. Fetched trees and files are cached under
.cache/mirror/; GitHub's API is reached through `gh api` when it is logged in, otherwise over
https (60 requests an hour without GITHUB_TOKEN).

Output: dist/mirrors/NAME/index.json and report.md. Re-running over the same commits writes
the same bytes: an entry whose files did not change keeps its commit and version, and the
list keeps its serial and expiry unless something changed or it expires within 30 days.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

import yaml

import repo as workshop

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "mirror"
CONFIG = ROOT / "mirrors.yml"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
AGENT = "duskcode-workshop-mirror"

# The owner's allow-list for mirrored skills; narrower than the Workshop's own (repo.py).
LICENSES = ("Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "CC-BY-4.0", "ISC")
# duskcode's caps (store/upstream.rs, store/index.rs, catalog/graph.rs).
MAX_FILES = 200
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_PATH = 300
MAX_ENTRIES = 2000
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_NODE_BYTES = 256 * 1024
MAX_DESCRIPTION = 1024
MAX_CREDIT = 64
MAX_URL = 200
# The store's entry names (index.rs is_plain_folder_name, check-index.py NAME), lower case.
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Names duskcode keeps for itself: its built-in skills (resources/skills) and the duskcode
# pack. An Unverified listing that is, or is one edit from, one of them is refused as taken
# (store/guard.rs `shadow`), so it is skipped here rather than listed dead.
# Words no listing of the Workshop carries beside the companies of repo.py: assistants'
# and agents' names. A skill whose name has one is listed under a neutral name, or skipped.
EXTRA_COMPANIES = ("anthropics", "claude", "chatgpt", "gpt", "gemini", "copilot", "codex", "hermes")
RESERVED = ("computer-use", "skill-creator", "skill-evolve", "token-thrift", "duskcode")
# Folders the skill graph never reads as nodes (graph.rs SKIPPED).
GRAPH_SKIPS = ("node_modules", "target", "venv", "__pycache__", "dist", "build")
PART = re.compile(r"^[A-Za-z0-9._-]+$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
LIFETIME = timedelta(days=180)
RENEW = timedelta(days=30)
INDEX_MAX_AGE = 24 * 3600
# Not worth downloading to find out: what these hold is never text.
BINARY = {"png", "jpg", "jpeg", "gif", "webp", "ico", "bmp", "tif", "tiff", "psd", "pdf", "zip", "gz",
          "tgz", "bz2", "xz", "zst", "tar", "7z", "rar", "jar", "war", "class", "so", "dylib", "dll", "exe",
          "bin", "o", "a", "wasm", "woff", "woff2", "ttf", "otf", "eot", "mp3", "mp4", "m4a", "wav", "ogg",
          "flac", "mov", "avi", "webm", "mkv", "pyc", "docx", "xlsx", "pptx", "dotx", "odt", "sqlite", "db",
          "npy", "npz", "pkl", "pt", "onnx", "safetensors", "parquet", "glb", "fbx", "blend", "icns"}
SCRIPTS = {"py", "sh", "bash", "zsh", "fish", "js", "mjs", "cjs", "ts", "mts", "rb", "pl", "php", "ps1",
           "bat", "cmd", "lua", "r", "go", "rs", "swift", "kt", "java", "cs"}
# Front matter that only Claude Code reads, and what to tell the user about each.
CLAUDE_FIELDS = {
    "allowed-tools": "allowed-tools (Claude Code only, grants nothing in Dusk)",
    "disallowed-tools": "disallowed-tools (Claude Code only)",
    "hooks": "hooks (Claude Code only, not installed)",
    "disable-model-invocation": "meant to run only as a /command in Claude Code",
    "model": "picks a Claude model (ignored)",
    "shell": "shell (Claude Code only)",
}
HERMES_FIELDS = {
    "required_environment_variables": "expects environment variables (Hermes asks for them, Dusk does not)",
}
INJECTION = re.compile(r"!`[^`\n]+`")
ARGUMENTS = re.compile(r"\$ARGUMENTS\b|\$\{?ARGUMENTS")
CLAUDE_PATHS = re.compile(r"\$\{CLAUDE_(?:SKILL_DIR|PLUGIN_ROOT|PROJECT_DIR)\}")
LICENSE_FILE = re.compile(r"^(?:LICEN[CS]E|COPYING)(?:[._-][A-Za-z0-9._-]*)?$", re.I)
ALIASES = {
    "apache-2.0": "Apache-2.0", "apache 2.0": "Apache-2.0", "apache2": "Apache-2.0", "apache-2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "apache license, version 2.0": "Apache-2.0", "apache 2": "Apache-2.0",
    "mit": "MIT", "mit license": "MIT", "the mit license": "MIT", "mit-0": "MIT-0",
    "bsd-2-clause": "BSD-2-Clause", "bsd 2-clause": "BSD-2-Clause", "bsd-3-clause": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause", "bsd-3": "BSD-3-Clause", "isc": "ISC", "cc-by-4.0": "CC-BY-4.0",
    "cc by 4.0": "CC-BY-4.0", "cc-by 4.0": "CC-BY-4.0",
}
# Words that send a skill to a category when its own text names none of the fixed list.
CATEGORY_WORDS = {
    "coding": "code coding api sdk mcp programming refactor git typescript python rust javascript frontend "
              "backend web react compiler cli library framework developer development software",
    "review": "review reviewer audit lint critique",
    "testing": "test testing tests qa playwright e2e unit pytest jest webapp-testing",
    "security": "security pentest vulnerability vulnerabilities secrets secret auth exploit threat malware",
    "research": "research paper papers science scientific academic literature arxiv biology chemistry",
    "writing": "writing write docs doc docx documentation blog copy comms article prose editor markdown",
    "data": "data excel xlsx csv sql analytics dataframe dataframes spreadsheet ml mlops statistics pdf",
    "devops": "deploy deployment docker kubernetes ci infra infrastructure devops cloud terraform aws",
    "design": "design art canvas theme brand gif image images video ui ux svg illustration diagram",
    "productivity": "productivity notes calendar tasks workflow planning",
    "devices": "ios android device devices iot simulator hardware",
    "communication": "email slack chat telegram discord message messages internal-comms",
}


SINGULAR = {"submodules": "submodule", "links": "link", "files with paths Dusk refuses": "file with a path Dusk refuses",
            "empty files": "empty file", "files over 4 MiB": "file over 4 MiB", "binary files": "binary file"}
# The notes that name a feature of another agent that Dusk lacks: what "flagged" counts.
FEATURES = tuple(CLAUDE_FIELDS.values()) + tuple(HERMES_FIELDS.values()) + (
    "context: fork", "uses $ARGUMENTS", "uses !`command`", "names ${CLAUDE_")


class Refused(Exception):
    """GitHub said no: rate limit, missing repository or file."""


class Skip(Exception):
    """This item is left out of the list, for the reason given."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


# GitHub ------------------------------------------------------------------------------


class GitHub:
    """GitHub's API through `gh api` when it is logged in, else over https; raw files from
    raw.githubusercontent.com, which has no API rate limit. Trees and files are cached by
    their hash, which never changes; a branch is looked up again on every run."""

    def __init__(self, use_gh=True):
        self.gh = use_gh and shutil.which("gh") is not None and subprocess.run(
            ["gh", "auth", "status"], capture_output=True).returncode == 0
        self.calls = 0
        self.repos, self.commits, self.trees = {}, {}, {}

    def api(self, path):
        self.calls += 1
        if self.gh:
            done = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github+json", path],
                                  capture_output=True, text=True)
            if done.returncode == 0:
                return json.loads(done.stdout)
            said = (done.stderr or done.stdout).strip().splitlines()
            said = said[-1] if said else "no answer"
            if "rate limit" in said.lower():
                raise SystemExit(f"GitHub's API rate limit is used up for this gh login ({said}); "
                                 f"wait for it to reset (gh api rate_limit) and run again")
            raise Refused(f"{path}: {said}")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": AGENT}
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{API}/{path}", headers=headers), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as error:
            if error.code in (403, 429) and error.headers.get("X-RateLimit-Remaining") == "0":
                reset = datetime.fromtimestamp(int(error.headers.get("X-RateLimit-Reset", "0")), timezone.utc)
                raise SystemExit(
                    f"GitHub's API rate limit ({error.headers.get('X-RateLimit-Limit')} requests an hour "
                    f"{'for GITHUB_TOKEN' if 'Authorization' in headers else 'without a token'}) is used up "
                    f"until {reset:%H:%M} UTC. Log in with `gh auth login` or set GITHUB_TOKEN, and run again.")
            raise Refused(f"{path}: HTTP {error.code}")
        except urllib.error.URLError as error:
            raise SystemExit(f"cannot reach {API}: {error.reason}")

    def repo(self, name):
        """The repository's canonical `owner/name` (GitHub follows a rename), default branch
        and licence as GitHub detects it."""
        if name not in self.repos:
            try:
                meta = self.api(f"repos/{name}")
            except Refused as error:
                self.repos[name] = error
            else:
                self.repos[name] = {"repo": meta["full_name"], "branch": meta["default_branch"],
                                    "license": (meta.get("license") or {}).get("spdx_id"),
                                    "owner": meta["owner"]["login"]}
        if isinstance(self.repos[name], Refused):
            raise Skip("repository not found", f"{name}: {self.repos[name]}")
        return self.repos[name]

    def commit(self, name, ref=None):
        """The commit `ref` (the default branch when none) names now, and its date."""
        meta = self.repo(name)
        ref = ref or meta["branch"]
        key = (meta["repo"], ref)
        if key not in self.commits:
            cached = CACHE / "commits" / meta["repo"].replace("/", "__") / f"{ref}.json"
            if COMMIT.match(ref) and cached.is_file():
                self.commits[key] = tuple(json.loads(cached.read_text()))
            else:
                try:
                    found = self.api(f"repos/{meta['repo']}/commits/{ref}")
                except Refused as error:
                    raise Skip("commit not found", f"{meta['repo']}@{ref}: {error}")
                self.commits[key] = (found["sha"], utc(found["commit"]["committer"]["date"]))
                if COMMIT.match(ref):
                    write(cached, json.dumps(self.commits[key]).encode())
        return meta["repo"], *self.commits[key]

    def tree(self, name, commit, folder=None):
        """Every blob, link and submodule of the repository at `commit`, by path. A
        repository too large for one answer of GitHub's is never walked whole: only the
        files of `folder` and the top level are listed, a few requests deep."""
        key = (name, commit, None)
        if key not in self.trees:
            folder_name = name.replace("/", "__")
            cached, too_large = CACHE / "trees" / folder_name / f"{commit}.json", \
                CACHE / "trees" / folder_name / f"{commit}.truncated"
            if cached.is_file():
                self.trees[key] = json.loads(cached.read_text())
            elif too_large.is_file():
                self.trees[key] = None
            else:
                found = self.api(f"repos/{name}/git/trees/{commit}?recursive=1")
                if found.get("truncated"):
                    write(too_large, b"")
                    self.trees[key] = None
                else:
                    self.trees[key] = files_of(found["tree"])
                    write(cached, json.dumps(self.trees[key], sort_keys=True).encode())
        if self.trees[key] is not None:
            return self.trees[key]
        if not folder:
            raise Skip("repository too large", f"{name}: GitHub lists only part of its tree, so it is not searched")
        return self.part(name, commit, folder)

    def part(self, name, commit, folder):
        """The top level and the files under `folder` of a repository too large to list."""
        key = (name, commit, folder)
        cached = CACHE / "trees" / name.replace("/", "__") / f"{commit}-{folder.replace('/', '%')}.json"
        if key in self.trees:
            return self.trees[key]
        if cached.is_file():
            self.trees[key] = json.loads(cached.read_text())
            return self.trees[key]
        top = self.api(f"repos/{name}/git/trees/{commit}")["tree"]
        listing, parts = top, folder.split("/")
        for depth, part in enumerate(parts):
            sha = next((item["sha"] for item in listing if item["path"] == part and item["type"] == "tree"), None)
            if sha is None:
                raise Skip("no SKILL.md", f"no folder {folder} in {name}@{commit[:7]}")
            if depth < len(parts) - 1:
                listing = self.api(f"repos/{name}/git/trees/{sha}")["tree"]
        found = self.api(f"repos/{name}/git/trees/{sha}?recursive=1")
        if found.get("truncated"):
            raise Skip("repository too large", f"{name}: even {folder} is too large for GitHub to list")
        tree = files_of(top)
        tree.update(files_of(found["tree"], f"{folder}/"))
        write(cached, json.dumps(tree, sort_keys=True).encode())
        self.trees[key] = tree
        return tree

    def raw(self, name, commit, path, blob):
        """The bytes of `path`, checked against the git blob hash the tree names."""
        cached = CACHE / "blobs" / blob[:2] / blob
        if cached.is_file():
            return cached.read_bytes()
        url = f"{RAW}/{name}/{commit}/{path}"
        for attempt in range(6):
            wait = 2 ** attempt
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}),
                                            timeout=60) as r:
                    data = r.read(MAX_FILE_BYTES + 1)
                break
            except urllib.error.HTTPError as error:
                # The raw host has no API quota but does slow down a burst (429).
                if (error.code != 429 and error.code < 500) or attempt == 5:
                    raise Skip("file not fetched", f"{path}: HTTP {error.code}")
                if error.code == 429:
                    wait = max(wait, min(int(error.headers.get("Retry-After") or 10), 120))
                    print(f"raw.githubusercontent.com asks to slow down; waiting {wait} s", file=sys.stderr)
            except (urllib.error.URLError, OSError) as error:
                if attempt == 5:
                    raise Skip("file not fetched", f"{path}: {error}")
            time.sleep(wait)
        if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != blob:
            raise Skip("file not fetched", f"{path}: the raw host's bytes are not the tree's blob")
        write(cached, data)
        return data


def files_of(items, prefix=""):
    return {f"{prefix}{item['path']}": {"type": item["type"], "mode": item["mode"], "sha": item["sha"],
                                        "size": item.get("size", 0)}
            for item in items if item["type"] != "tree"}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}")
    temp.write_bytes(data)
    temp.replace(path)


def utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc) \
        .replace(microsecond=0).isoformat().replace("+00:00", "Z")


# One skill ---------------------------------------------------------------------------


class Candidate:
    """A skill folder at a pinned commit, and what the catalogue says about it."""

    def __init__(self, ident, repo, commit, date, folder, tree, author=None, tags=(), meta=None):
        self.ident, self.repo, self.commit, self.date, self.folder = ident, repo, commit, date, folder
        self.tree, self.author, self.tags, self.meta = tree, author, list(tags), meta or {}


def plain_path(path):
    return 0 < len(path.encode()) <= MAX_PATH and all(
        part not in (".", "..") and PART.match(part) for part in path.split("/"))


class DupLoader(yaml.SafeLoader):
    """YAML that refuses a key given twice, as duskcode's parser does."""


def _mapping(loader, node, deep=False):
    keys = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in keys:
            raise yaml.constructor.ConstructorError(None, None, f"the key {key!r} is given twice",
                                                    key_node.start_mark)
        keys.add(key)
    return loader.construct_mapping(node, deep)


DupLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def split_front(text):
    """graph.rs split_front_matter: `---` on the first line, up to the next `---` line."""
    for opener in ("---\n", "---\r\n"):
        if text.startswith(opener):
            rest = text[len(opener):]
            break
    else:
        raise Skip("will not load", "SKILL.md does not start with a --- front matter line")
    offset = 0
    # Lines end at "\n" only, as Rust's split_inclusive('\n'); str.splitlines would also
    # end them at characters such as U+2028.
    for line in re.findall(r"[^\n]*\n|[^\n]+$", rest):
        if line.rstrip() == "---":
            return rest[:offset], rest[offset + len(line):]
        offset += len(line)
    raise Skip("will not load", "SKILL.md's front matter has no closing --- line")


def read_front(data, name=None):
    """The front matter as duskcode reads a skill (graph.rs parse_node), or why it will not
    load as the node `name` (any name the front matter declares, when None)."""
    if len(data) > MAX_NODE_BYTES:
        raise Skip("will not load", f"SKILL.md is over {MAX_NODE_BYTES} bytes")
    text = data.decode()
    front_text, body = split_front(text)
    try:
        front = yaml.load(front_text, Loader=DupLoader)
    except yaml.YAMLError as error:
        said = str(error).splitlines()[0][:160]
        raise Skip("will not load", f"front matter is not valid YAML: {said}")
    if not isinstance(front, dict):
        raise Skip("will not load", "front matter is not a mapping")
    if not isinstance(front.get("description"), str):
        raise Skip("will not load", "no description in front matter")
    description = " ".join(front["description"].split())
    if not description:
        raise Skip("will not load", "description is empty")
    if len(description) > MAX_DESCRIPTION:
        raise Skip("will not load", f"description is longer than {MAX_DESCRIPTION} characters")
    declared = front.get("name")
    if name is not None and declared is not None and declared != name:
        raise Skip("name differs from folder", f"front matter names {str(declared)[:64]!r}, the folder is {name}")
    strings = lambda value: isinstance(value, list) and all(isinstance(item, str) for item in value)
    for key in ("links", "skills", "tags"):
        if key in front and not strings(front[key]):
            raise Skip("will not load", f"{key} is not a list of words")
    if "tools" in front and front["tools"] is not None and not strings(front["tools"]):
        raise Skip("will not load", "tools is not a list of words")
    if "entry" in front and not isinstance(front["entry"], bool):
        raise Skip("will not load", "entry is not true or false")
    if "source" in front and front["source"] is not None and not isinstance(front["source"], str):
        raise Skip("will not load", "source is not text")
    return front, description, body


def spdx(text):
    """An SPDX expression of `text`, ids joined by AND or OR, or None when it is not one."""
    if not isinstance(text, str):
        return None
    text = text.strip().strip("()")
    if text.lower() in ALIASES:
        return ALIASES[text.lower()]
    if re.search(r"licen[cs]e|copying|\.txt|\.md|terms", text, re.I):
        return None
    parts = text.split()
    if len(parts) % 2 == 1 and all(p in ("AND", "OR") for p in parts[1::2]) \
            and all(re.match(r"^[A-Za-z0-9.+-]+$", p) and any(c.isdigit() or c.isupper() for c in p)
                    for p in parts[::2]):
        return " ".join(ALIASES.get(p.lower(), p) for p in parts)
    return None


def allowed(expression):
    parts = expression.split()
    return all(p in LICENSES for p in parts[::2])


def license_of(text):
    """The licence a licence file's text is, or None when it is not one recognised."""
    flat = " ".join(text.split()).lower()
    if "apache license" in flat and "version 2.0" in flat:
        return "Apache-2.0"
    if "permission is hereby granted, free of charge" in flat and "without restriction" in flat:
        return "MIT"
    if "redistribution and use in source and binary forms" in flat:
        return "BSD-3-Clause" if "neither the name" in flat or "may be used to endorse" in flat else "BSD-2-Clause"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in flat:
        return "ISC" if "above copyright notice and this permission notice appear" in flat else "0BSD"
    if "attribution 4.0 international" in flat and "creative commons" in flat:
        return "CC-BY-4.0" if "noncommercial" not in flat and "noderivatives" not in flat else "CC-BY-NC-ND"
    for word, name in (("gnu general public license", "GPL"), ("gnu lesser general public", "LGPL"),
                       ("gnu affero", "AGPL"), ("mozilla public license", "MPL-2.0"),
                       ("this is free and unencumbered software", "Unlicense"),
                       ("cc0 1.0 universal", "CC0-1.0"), ("all rights reserved", "proprietary")):
        if word in flat:
            return name
    return None


def find_license(c, front, bodies, fetch):
    """The skill's licence, and the repository's licence files to pin into its folder when
    the licence is the repository's: its front matter's when that is an SPDX expression;
    else a licence file in its folder; else the repository's licence files (all of them,
    joined with AND), or the licence GitHub detects for the repository."""
    metadata = front.get("metadata") if isinstance(front.get("metadata"), dict) else {}
    declared = spdx(front.get("license")) or spdx(metadata.get("license"))
    if declared:
        if not allowed(declared):
            raise Skip("licence not allowed", declared)
        return declared, []
    if isinstance(front.get("license"), str) and re.search(
            r"proprietar|all rights reserved|non-?commercial|\bgpl\b|source[- ]available", front["license"], re.I):
        raise Skip("licence not allowed", " ".join(front["license"].split())[:60])
    own = sorted(rel for rel in bodies if "/" not in rel and LICENSE_FILE.match(rel))
    for rel in own:
        found = license_of(bodies[rel].decode())
        if found:
            if found not in LICENSES:
                raise Skip("licence not allowed", f"{found} ({rel})")
            return found, []
    if own:
        raise Skip("licence not recognised", f"{own[0]} in the skill's folder")
    root = sorted(p for p in c.tree if "/" not in p and LICENSE_FILE.match(p) and c.tree[p]["type"] == "blob"
                  and 0 < c.tree[p]["size"] <= MAX_FILE_BYTES)
    recognised = {p: license_of(fetch(p).decode("utf-8", "replace")) for p in root}
    recognised = {p: found for p, found in recognised.items() if found}
    if recognised:
        refused = sorted({found for found in recognised.values() if found not in LICENSES})
        if refused:
            raise Skip("licence not allowed", f"{', '.join(refused)} (the repository's)")
        # Several licence files (text under one, code under another) bind together.
        return " AND ".join(sorted(set(recognised.values()))), sorted(recognised)
    detected = c.meta.get("repo_license")
    detected = detected if detected not in (None, "NOASSERTION", "NONE", "other") else None
    if not detected:
        raise Skip("no licence", "none in the front matter, the skill's folder or the repository")
    if detected not in LICENSES:
        raise Skip("licence not allowed", f"{detected} (the repository's)")
    return detected, root[:1]


def is_text(data):
    """UTF-8 without NUL, as store/upstream.rs `assemble` requires of every file."""
    try:
        data.decode()
    except UnicodeDecodeError:
        return False
    return b"\0" not in data


def plain_line(text, limit):
    return isinstance(text, str) and text.strip() == text and 0 < len(text) <= limit and not any(
        ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F or 0x202A <= ord(ch) <= 0x202E or 0x2066 <= ord(ch) <= 0x2069
        for ch in text)


def tag_words(values):
    tags = []
    for value in values:
        if not isinstance(value, str):
            continue
        word = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:32].strip("-")
        if word and word not in tags:
            tags.append(word)
    return tags[:8]


def categories_of(name, tags, description, fallback):
    words = set(re.split(r"[^a-z0-9-]+", f"{name} {' '.join(tags)}".lower())) | set(name.split("-"))
    text = set(re.split(r"[^a-z0-9-]+", description.lower()))
    scores = []
    for index, (category, keys) in enumerate(CATEGORY_WORDS.items()):
        keys = set(keys.split())
        score = 3 * len(words & keys) + len(text & keys)
        if score:
            scores.append((-score, index, category))
    scores.sort()
    found = [category for score, _, category in scores[:2] if score * 2 <= scores[0][0]]
    return found or list(fallback)


def close(a, b):
    """store/guard.rs `close`: the same name, or one edit apart once case and dashes are
    left out, for names of at least 5 such letters."""
    a, b = a.replace("-", "").lower(), b.replace("-", "").lower()
    if a == b:
        return True
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    short, long = sorted((a, b), key=len)
    start = next((i for i, (x, y) in enumerate(zip(short, long)) if x != y), len(short))
    return short[start + 1:] == long[start + 1:] if len(short) == len(long) else short[start:] == long[start + 1:]


def company_word(name):
    """A company or product word in `name`: the Workshop's list (repo.py) and the names of
    assistants, which are no listing's to carry."""
    words = set(re.split(r"[^a-z0-9]+", name.lower()))
    return next((w for w in tuple(workshop.COMPANIES) + EXTRA_COMPANIES if w in words), None)


def entry_name(folder_name, front):
    """The name the skill is listed and installed under, and a note when that is not its
    upstream folder's: its front matter's name when it declares one, since duskcode loads
    a skill only under the name it declares; a company's word is taken out of a name the
    front matter does not fix, and a skill whose declared name carries one is skipped."""
    declared = front.get("name")
    name = declared if isinstance(declared, str) else folder_name
    if declared is not None and not isinstance(declared, str):
        raise Skip("will not load", "its front matter's name is not text")
    note = f"listed as {name}, the name its front matter declares; the upstream folder is {folder_name}" \
        if name != folder_name else None
    word = company_word(name)
    if word and isinstance(declared, str):
        raise Skip("company in name", f"{name} carries {word}, and its front matter declares that name, "
                                      "so it cannot be listed under a neutral one")
    if word:
        neutral = "-".join(part for part in name.split("-") if not company_word(part))
        if len(neutral) < 3:
            raise Skip("company in name", f"{name} carries {word}, and no neutral name is left without it")
        name, note = neutral, f"listed as {neutral}; the upstream folder is {folder_name}"
    if not NAME.match(name):
        raise Skip("name not allowed", f"{name[:64]!r}: a-z, 0-9, - and _, at most 64, starting with a letter or digit")
    taken = next((r for r in RESERVED if close(name, r)), None)
    if taken:
        raise Skip("name taken in Dusk", f"{name} is or is too close to Dusk's own {taken}")
    if name in GRAPH_SKIPS:
        raise Skip("name not allowed", f"{name}: Dusk's skill graph never reads a folder of that name")
    return name, note


def convert(gh, c, fallback):
    """The list entry of candidate `c`, with its notes; or Skip."""
    folder_name = c.folder.rsplit("/", 1)[-1] if c.folder else c.repo.split("/")[1]
    if c.folder and not plain_path(c.folder):
        raise Skip("path not allowed", f"{c.folder}: only A-Z, a-z, 0-9, ., _ and - in a path")
    prefix = f"{c.folder}/" if c.folder else ""
    if f"{prefix}SKILL.md" not in c.tree:
        raise Skip("no SKILL.md", f"{c.repo}@{c.commit[:7]}:{c.folder or '/'}")
    found = {path[len(prefix):]: item for path, item in c.tree.items() if path.startswith(prefix)}
    if not c.folder:
        # A skill at the top of a repository: not the other skills of that repository.
        others = {rel.rsplit("/", 1)[0] for rel in found if rel.endswith("/SKILL.md")}
        found = {rel: item for rel, item in found.items() if not any(rel.startswith(f"{o}/") for o in others)}
    left = Counter()
    keep = {}
    for rel, item in sorted(found.items()):
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel.rsplit("/", 1)[-1] else ""
        if item["type"] == "commit":
            left["submodules"] += 1
        elif item["mode"] == "120000":
            left["links"] += 1
        elif not plain_path(rel) or not plain_path(f"{prefix}{rel}"):
            left["files with paths Dusk refuses"] += 1
        elif item["size"] == 0:
            left["empty files"] += 1
        elif item["size"] > MAX_FILE_BYTES:
            left["files over 4 MiB"] += 1
        elif ext in BINARY:
            left["binary files"] += 1
        else:
            keep[rel] = item
    if "SKILL.md" not in keep:
        raise Skip("will not load", "SKILL.md cannot be pinned (empty, too big or a link)")
    fetch = lambda path: gh.raw(c.repo, c.commit, path, c.tree[path]["sha"])
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        bodies = dict(zip(keep, pool.map(lambda rel: fetch(f"{prefix}{rel}"), keep)))
    for rel in list(keep):
        if not is_text(bodies[rel]):
            if rel == "SKILL.md":
                raise Skip("will not load", "SKILL.md is not UTF-8 text")
            left["binary files"] += 1
            del keep[rel], bodies[rel]
    front, description, body = read_front(bodies["SKILL.md"])
    name, renamed = entry_name(folder_name, front)
    for rel in list(keep):
        if not plain_path(f"{name}/{rel}"):
            left["files with paths Dusk refuses"] += 1
            del keep[rel], bodies[rel]
    license, extras = find_license(c, front, bodies, fetch)
    files = [(f"{prefix}{rel}", f"{name}/{rel}", bodies[rel]) for rel in keep]
    for extra in extras:
        to = f"{name}/{extra.rsplit('/', 1)[-1]}"
        if to not in {t for _, t, _ in files} and is_text(fetch(extra)):
            files.append((extra, to, fetch(extra)))
    if len(files) > MAX_FILES:
        raise Skip("too many files", f"{len(files)} text files, at most {MAX_FILES}")

    notes = []
    for key, note in {**CLAUDE_FIELDS, **HERMES_FIELDS}.items():
        if key in front:
            notes.append(note)
    if front.get("context") == "fork":
        notes.append("context: fork (Claude Code runs it in a sub-agent; Dusk does not)")
    if ARGUMENTS.search(body):
        notes.append("uses $ARGUMENTS, which Dusk does not fill in")
    if INJECTION.search(body):
        notes.append("uses !`command` injection, which Dusk does not run")
    if CLAUDE_PATHS.search(body):
        notes.append("names ${CLAUDE_...} folders, which Dusk does not fill in")
    nested = sorted(rel for rel in keep if rel != "SKILL.md" and rel.endswith("/SKILL.md"))
    if nested:
        notes.append(f"holds {len(nested)} more SKILL.md, read as skills of their own")
    scripts = sum(1 for rel in keep if rel.rsplit(".", 1)[-1].lower() in SCRIPTS
                  or bodies[rel][:2] == b"#!")
    if scripts:
        notes.append(f"{scripts} {'script' if scripts == 1 else 'scripts'} the agent may ask to run")
    for what, count in sorted(left.items()):
        notes.append(f"{count} {what if count > 1 else SINGULAR.get(what, what)} left out of the pin "
                     "(they stay in the upstream folder)")
    if "name" not in front:
        notes.append("no name in its front matter")
    if renamed:
        notes.append(renamed)

    author = None
    for value in (front.get("author"), (front.get("metadata") or {}).get("author")
                  if isinstance(front.get("metadata"), dict) else None, c.author):
        if isinstance(value, str) and plain_line(" ".join(value.split()), MAX_CREDIT):
            author = " ".join(value.split())
            break
    author = author or c.repo.split("/")[0]
    hermes = (front.get("metadata") or {}).get("hermes") if isinstance(front.get("metadata"), dict) else None
    hermes_tags = hermes.get("tags") if isinstance(hermes, dict) else None
    tags = tag_words((front.get("tags") or []) + (hermes_tags if isinstance(hermes_tags, list) else []) + c.tags)
    categories = categories_of(name, tags, description, fallback)
    text = f"{description} Not affiliated with or endorsed by {author}."
    if notes:
        text += " Notes: " + "; ".join(notes) + "."
    tree_url = f"https://github.com/{c.repo}/tree/{c.commit}" + (f"/{c.folder}" if c.folder else "")
    entry = {
        "name": name,
        "version": "1." + c.date[:10].replace("-", "") + ".0",
        "kind": "skill",
        "description": text,
        "homepage": tree_url,
        "category": categories[0],
        "tags": tags,
        "created": c.date,
        "updated": c.date,
        "author": author,
        "license": license,
        "source": tree_url if len(tree_url) <= MAX_URL else f"https://github.com/{c.repo}",
        "categories": categories,
        "badge": "verified",
        "upstream": {
            "repo": c.repo,
            "commit": c.commit,
            "files": [{"path": path, "to": to, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                      for path, to, data in sorted(files, key=lambda f: f[1])],
        },
    }
    return entry, notes


# Catalogues --------------------------------------------------------------------------


def window(items, args):
    """The items --offset and --limit pick."""
    items = items[args.offset:]
    return items[:args.limit] if args.limit else items


def matches(pattern, *texts):
    return pattern is None or any(pattern.search(t or "") for t in texts)


def skills_repo(gh, cfg, args, out):
    """Every folder holding a SKILL.md under `path`; a SKILL.md inside another skill's
    folder belongs to that skill."""
    repo, commit, date = gh.commit(cfg["repo"], cfg.get("ref"))
    try:
        tree = gh.tree(repo, commit)
    except Skip as skip:
        raise SystemExit(f"{cfg['name']}: {skip.detail}")
    base = cfg.get("path", "").strip("/")
    folders = skill_folders(tree, base)
    meta = {"repo_license": gh.repo(repo)["license"]}
    picked = [f for f in folders if matches(args.match, f.rsplit("/", 1)[-1], f)]
    for folder in window(picked, args):
        out.consider(gh, Candidate(f"{repo}/{folder}", repo, commit, date, folder, tree,
                                   author=cfg.get("author"), meta=meta), cfg)


def skill_folders(tree, base=""):
    """The folders under `base` that hold a SKILL.md, outermost only: one inside another
    skill's folder is part of that skill. A SKILL.md at the top of the repository is a
    skill of its own beside the others."""
    prefix = f"{base}/" if base else ""
    folders = sorted(p[:-len("SKILL.md")].rstrip("/") for p in tree
                     if tree[p]["type"] == "blob" and p.startswith(prefix) and (p == "SKILL.md" or p.endswith("/SKILL.md")))
    outer = []
    for folder in folders:
        if not any(o and folder.startswith(f"{o}/") for o in outer):
            outer.append(folder)
    return outer


def github_repo(url):
    found = re.match(r"^(?:https://github\.com/|git@github\.com:)([A-Za-z0-9._-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$",
                     url or "")
    return found.group(1) if found else None


def claude_marketplace(gh, cfg, args, out):
    """The skills/ folders of each plugin of a Claude Code marketplace: a plugin in this
    repository, or in another GitHub repository at the commit the marketplace pins."""
    repo, commit, date = gh.commit(cfg["repo"], cfg.get("ref"))
    tree = gh.tree(repo, commit)
    path = ".claude-plugin/marketplace.json"
    if path not in tree:
        raise SystemExit(f"{repo}@{commit[:7]} has no {path}")
    market = json.loads(gh.raw(repo, commit, path, tree[path]["sha"]))
    owner = (market.get("owner") or {}).get("name")
    plugins = [p for p in market.get("plugins", []) if isinstance(p, dict) and matches(args.match, p.get("name"))]
    for plugin in window(plugins, args):
        pname = str(plugin.get("name", "?"))
        source = plugin.get("source")
        author = (plugin.get("author") or {}).get("name") if isinstance(plugin.get("author"), dict) else None
        try:
            if isinstance(source, str):
                if not source.startswith("./"):
                    raise Skip("plugin not on GitHub", f"source {source[:80]}")
                prepo, pcommit, pdate, ptree, root = repo, commit, date, tree, source[2:].strip("/")
            elif isinstance(source, dict) and source.get("source") in ("github", "url", "git-subdir"):
                where = source.get("repo") if source["source"] == "github" else github_repo(source.get("url"))
                if not where:
                    raise Skip("plugin not on GitHub", f"{source['source']} {str(source.get('url'))[:80]}")
                pin = source.get("sha") if COMMIT.match(str(source.get("sha", ""))) else source.get("ref")
                prepo, pcommit, pdate = gh.commit(where, pin)
                root = (source.get("path") or "").strip("/") if source["source"] == "git-subdir" else ""
                ptree = gh.tree(prepo, pcommit, root or None)
            else:
                kind = source.get("source") if isinstance(source, dict) else type(source).__name__
                raise Skip("plugin not on GitHub", f"a {kind} source (npm, archive and command are not taken)")
            folders = plugin_skills(plugin, ptree, root)
            if not folders:
                raise Skip("plugin brings no skills", "only MCP servers, hooks, commands or agents, which are not taken")
        except Skip as skip:
            out.skip(f"plugin {pname}", skip)
            continue
        meta = {"repo_license": gh.repo(prepo)["license"]}
        for folder in folders:
            out.consider(gh, Candidate(f"{pname}/{folder.rsplit('/', 1)[-1]}", prepo, pcommit, pdate, folder,
                                       ptree, author=author or owner, meta=meta), cfg)


def plugin_skills(plugin, tree, root):
    """The skill folders a plugin brings: those its entry lists, else <root>/skills/*."""
    prefix = f"{root}/" if root else ""
    listed = plugin.get("skills")
    if isinstance(listed, str):
        listed = [listed]
    folders = []
    for item in listed if isinstance(listed, list) else ["./skills"]:
        if not isinstance(item, str):
            continue
        base = prefix + item.lstrip("./").strip("/") if item.strip("./") else root
        base = base.strip("/")
        if f"{base}/SKILL.md" in tree:
            folders.append(base)
        else:
            folders += [p[:-len("/SKILL.md")] for p in tree if p.startswith(f"{base}/")
                        and p.endswith("/SKILL.md") and p.count("/") == base.count("/") + 2]
    return sorted(set(folders))


def stream_entries(file):
    """The entries of the `skills` array of a large JSON index, one at a time, without
    reading the whole file into memory."""
    decoder = json.JSONDecoder()
    with open(file, encoding="utf-8") as handle:
        buffer, pos = "", 0
        while True:
            more = handle.read(1 << 16)
            buffer += more
            start = re.search(r'"skills"\s*:\s*\[', buffer)
            if start:
                pos = start.end()
                break
            if not more:
                raise SystemExit(f"{file}: no skills array")
            buffer = buffer[-64:]
        while True:
            while pos < len(buffer) and buffer[pos] in " \t\r\n,":
                pos += 1
            if pos >= len(buffer):
                more = handle.read(1 << 16)
                if not more:
                    raise SystemExit(f"{file}: the skills array does not end")
                buffer, pos = buffer[pos:] + more, 0
                continue
            if buffer[pos] == "]":
                return
            try:
                item, end = decoder.raw_decode(buffer, pos)
            except json.JSONDecodeError:
                more = handle.read(1 << 16)
                if not more:
                    raise
                buffer, pos = buffer[pos:] + more, 0
                continue
            yield item
            pos = end
            if pos > 1 << 20:
                buffer, pos = buffer[pos:], 0


def hermes_file(url, refresh):
    cached = CACHE / "hermes" / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".json")
    if cached.is_file() and not refresh and time.time() - cached.stat().st_mtime < INDEX_MAX_AGE:
        return cached
    print(f"fetching {url}", file=sys.stderr)
    cached.parent.mkdir(parents=True, exist_ok=True)
    temp = cached.with_name(cached.name + ".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=300) as r, \
            open(temp, "wb") as handle:
        shutil.copyfileobj(r, handle, 1 << 20)
    temp.replace(cached)
    return cached


def hermes_index(gh, cfg, args, out):
    """Hermes Agent's skills index: each entry resolved to a GitHub folder, pinned to the
    commit its repository's branch names now. ClawHub and LobeHub entries name no GitHub
    location, so they are skipped; skills.sh entries name a repository and a skill name,
    found in that repository's tree."""
    seen = 0
    for item in stream_entries(hermes_file(cfg["url"], args.refresh)):
        ident = str(item.get("identifier") or item.get("name") or "?")
        if not matches(args.match, ident, item.get("name"), item.get("repo"), item.get("source")):
            continue
        seen += 1
        if seen <= args.offset:
            continue
        if args.limit and seen > args.offset + args.limit:
            break
        try:
            candidate = hermes_candidate(gh, item, ident)
        except Skip as skip:
            out.skip(ident, skip)
            continue
        out.consider(gh, candidate, cfg)


def hermes_location(item):
    """Where on GitHub an entry of the Hermes index is: (repository, ref, folder), the ref
    None for the default branch and the folder None when only the skill's name is known."""
    source, extra = item.get("source"), item.get("extra") or {}
    if source in ("official", "github") and item.get("repo"):
        return item["repo"], None, (item.get("path") or "").strip("/")
    if source == "skills.sh" and item.get("resolved_github_id"):
        parts = item["resolved_github_id"].split("/")
        return "/".join(parts[:2]), None, "/".join(parts[2:])
    if source == "skills.sh" and item.get("repo"):
        return item["repo"], None, None
    if str(extra.get("source_url", "")).startswith("https://github.com/"):
        found = re.match(r"^https://github\.com/([^/]+/[^/]+)/(?:blob|tree)/([^/]+)/(.+?)(?:/SKILL\.md)?$",
                         extra["source_url"])
        if not found:
            raise Skip("no GitHub location", extra["source_url"][:120])
        return found.group(1), found.group(2), found.group(3)
    raise Skip("no GitHub location", f"a {source} entry names no repository (that hub hosts its files itself)")


def hermes_survey(cfg, args):
    """How many entries of the index can be converted at all, by hub: no network but the
    index itself."""
    counts = Counter()
    for item in stream_entries(hermes_file(cfg["url"], args.refresh)):
        ident = str(item.get("identifier") or item.get("name") or "?")
        if not matches(args.match, ident, item.get("name"), item.get("repo"), item.get("source")):
            continue
        try:
            hermes_location(item)
            counts[(str(item.get("source")), "on GitHub")] += 1
        except Skip:
            counts[(str(item.get("source")), "no GitHub location")] += 1
    lines = [f"# Survey: {cfg['name']}", "", f"`{cfg['url']}`", "", "| Hub | Entries | On GitHub | No GitHub location |",
             "|---|---|---|---|"]
    for hub in sorted({hub for hub, _ in counts}, key=lambda h: -sum(v for (k, _), v in counts.items() if k == h)):
        on, off = counts[(hub, "on GitHub")], counts[(hub, "no GitHub location")]
        lines.append(f"| {hub} | {on + off} | {on} | {off} |")
    on = sum(v for (_, where), v in counts.items() if where == "on GitHub")
    lines += ["", f"{sum(counts.values())} entries; {on} name a GitHub location and can be converted with "
                  "--match/--limit (subject to the checks), the rest cannot be pinned from GitHub."]
    print("\n".join(lines))


def hermes_candidate(gh, item, ident):
    extra = item.get("extra") or {}
    repo_name, ref, folder = hermes_location(item)
    repo, commit, date = gh.commit(repo_name, ref)
    tree = gh.tree(repo, commit, folder)
    if folder is None:
        want = item.get("path") or item.get("name")
        found = sorted((p[:-len("/SKILL.md")] for p in tree if p.endswith(f"/{want}/SKILL.md")
                        or p == f"{want}/SKILL.md"), key=lambda p: (p.count("/"), p))
        if not found:
            raise Skip("no SKILL.md", f"no folder {want} with a SKILL.md in {repo}@{commit[:7]}")
        folder = found[0]
    author = extra.get("provider") or extra.get("owner")
    meta = {"repo_license": gh.repo(repo)["license"]}
    return Candidate(ident, repo, commit, date, folder, tree, author=author,
                     tags=item.get("tags") or [], meta=meta)


KINDS = {"skills-repo": skills_repo, "claude-marketplace": claude_marketplace, "hermes-index": hermes_index}


# The list ----------------------------------------------------------------------------


class Run:
    """What one mirror took and skipped."""

    def __init__(self, previous):
        self.entries, self.taken, self.skipped = {}, [], []
        # What the list will weigh, as build_index writes it, against duskcode's cap.
        self.bytes = 200
        self.previous = {e["name"]: e for e in previous.get("plugins", [])}

    def skip(self, ident, skip):
        self.skipped.append((skip.code, ident, skip.detail))

    def consider(self, gh, candidate, cfg):
        try:
            entry, notes = convert(gh, candidate, cfg.get("categories") or ["productivity"])
            other = self.entries.get(entry["name"])
            if other:
                raise Skip("name taken", f"{entry['name']} is already {other['upstream']['repo']}")
            text = json.dumps(entry, indent=2, ensure_ascii=False)
            weight = len(text.encode()) + 4 * (text.count("\n") + 1) + 2
            if len(self.entries) >= MAX_ENTRIES or self.bytes + weight > MAX_INDEX_BYTES:
                raise Skip("list full", f"a list holds at most {MAX_ENTRIES} entries and {MAX_INDEX_BYTES} bytes; "
                                        "take the rest with --offset, or narrow --match")
        except Skip as skip:
            self.skip(candidate.ident, skip)
            return
        before = self.previous.get(entry["name"])
        if before and same_files(before, entry):
            # Nothing it installs changed: keep the commit and version users have.
            for key in ("version", "created", "updated", "homepage", "source"):
                entry[key] = before[key]
            entry["upstream"] = before["upstream"]
        elif before:
            entry["created"] = before.get("created", entry["created"])
        self.entries[entry["name"]] = entry
        self.bytes += weight
        self.taken.append((entry, candidate, notes))


def same_files(before, after):
    files = lambda e: [(f["to"], f["sha256"], f["size"]) for f in e["upstream"]["files"]]
    return before.get("upstream", {}).get("repo") == after["upstream"]["repo"] and files(before) == files(after) \
        and {k: v for k, v in before.items() if k not in ("version", "created", "updated", "homepage", "source",
                                                          "upstream")} \
        == {k: v for k, v in after.items() if k not in ("version", "created", "updated", "homepage", "source",
                                                        "upstream")}


def build_index(run, previous, now):
    plugins = [run.entries[name] for name in sorted(run.entries)]
    changed = plugins != previous.get("plugins")
    expires = previous.get("expires")
    stale = not expires or datetime.fromisoformat(expires.replace("Z", "+00:00")) - now < RENEW
    if changed or stale:
        serial = previous.get("serial", 0) + 1
        expires = (now + LIFETIME).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    else:
        serial = previous["serial"]
    index = {"format": 3, "serial": serial, "expires": expires, "plugins": plugins}
    data = (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode()
    if len(data) > MAX_INDEX_BYTES:
        raise SystemExit(f"the list is {len(data)} bytes, over duskcode's {MAX_INDEX_BYTES}; narrow --match or --limit")
    return data


def flagged_notes(notes):
    return [n for n in notes if n.startswith(FEATURES)]


def table_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def report(name, cfg, run, args):
    lines = [f"# Mirror report: {name}", ""]
    where = cfg.get("repo") or cfg.get("url")
    lines.append(f"Kind `{cfg['kind']}`, from `{where}`" + (f", path `{cfg['path']}`" if cfg.get("path") else "") + ".")
    slice_ = [f"--match {args.match.pattern!r}" if args.match else "", f"--offset {args.offset}" if args.offset else "",
              f"--limit {args.limit}" if args.limit else ""]
    if any(slice_):
        lines.append(f"Slice: {' '.join(s for s in slice_ if s)}.")
    pins = sorted({(e['upstream']['repo'], e['upstream']['commit']) for e, _, _ in run.taken})
    if pins and len(pins) <= 5:
        lines.append("Pinned: " + ", ".join(f"`{r}@{c[:7]}`" for r, c in pins) + ".")
    elif pins:
        lines.append(f"Pinned: {len(pins)} repositories.")
    flagged = [t for t in run.taken if flagged_notes(t[2])]
    lines += ["", f"**Taken {len(run.taken)} · skipped {len(run.skipped)} · flagged {len(flagged)}** "
                  "(flagged: taken, but using a feature of Claude Code or Hermes that Dusk lacks; every note is also in the entry's description)", ""]
    if run.taken:
        lines += ["## Taken", "", "| Skill | Upstream | Files | Licence | Author | Notes |", "|---|---|---|---|---|---|"]
        for entry, candidate, notes in sorted(run.taken, key=lambda t: t[0]["name"]):
            up = entry["upstream"]
            lines.append(f"| {entry['name']} | `{up['repo']}@{up['commit'][:7]}:{candidate.folder}` | "
                         f"{len(up['files'])} | {entry['license']} | {table_cell(entry['author'])} | "
                         f"{table_cell('; '.join(notes)) or ''} |")
        lines.append("")
    if run.skipped:
        counts = Counter(code for code, _, _ in run.skipped)
        lines += ["## Skip reasons", "", "| Reason | Count |", "|---|---|"]
        lines += [f"| {code} | {count} |" for code, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        lines += ["", "## Skipped", "", "| Item | Reason | Detail |", "|---|---|---|"]
        for code, ident, detail in sorted(run.skipped):
            lines.append(f"| {table_cell(ident[:100])} | {code} | {table_cell(detail[:200])} |")
        lines.append("")
    return "\n".join(lines)


def load_config():
    config = yaml.safe_load(CONFIG.read_text()) or {}
    mirrors = config.get("mirrors") or []
    names = set()
    for m in mirrors:
        if not isinstance(m, dict) or not workshop.PACK_NAME.match(str(m.get("name", ""))) or m["name"] in names:
            raise SystemExit(f"mirrors.yml: each mirror has a unique name of a-z, 0-9 and -: {m}")
        names.add(m["name"])
        if m.get("kind") not in KINDS:
            raise SystemExit(f"mirrors.yml: {m['name']}: kind is one of {', '.join(KINDS)}")
        if m["kind"] == "hermes-index" and not str(m.get("url", "")).startswith("https://"):
            raise SystemExit(f"mirrors.yml: {m['name']}: a hermes-index mirror names its index's https url")
        if m["kind"] != "hermes-index" and not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", str(m.get("repo", ""))):
            raise SystemExit(f"mirrors.yml: {m['name']}: repo is owner/name on GitHub")
        if company_word(m["name"]):
            raise SystemExit(f"mirrors.yml: {m['name']}: a mirror's name says what it holds, not whose it is")
        if set(m.get("categories") or []) - set(workshop.CATEGORIES):
            raise SystemExit(f"mirrors.yml: {m['name']}: categories are from {' '.join(workshop.CATEGORIES)}")
    return mirrors


PINNED = ROOT / "pinned"
PIN_FIELDS = {"name", "title", "description", "vendor", "kind", "license", "repo", "commit", "items"}


def pin(gh, folder, bump):
    """pinned/<pack>/pins.json: the files of each item of the pack at its commit, taken by
    the same rules as a mirror's skills, for the official list (scripts/publish.py). With
    `bump`, the pack moves to the commit its repository's default branch names now; review
    the diff of pins.json before it is signed."""
    file = folder / "pack.yml"
    pack = yaml.safe_load(file.read_text())
    if not isinstance(pack, dict) or set(pack) != PIN_FIELDS or not isinstance(pack["items"], dict):
        raise SystemExit(f"{file}: holds exactly {', '.join(sorted(PIN_FIELDS))}; items maps each item to its folder")
    repo, commit, date = gh.commit(pack["repo"], None if bump else pack["commit"])
    if repo != pack["repo"]:
        raise SystemExit(f"{file}: {pack['repo']} is now {repo} on GitHub; write the new name")
    if bump and commit != pack["commit"]:
        text = file.read_text().replace(pack["commit"], commit)
        file.write_text(text)
        print(f"{folder.name}: {pack['commit'][:7]} -> {commit[:7]}", file=sys.stderr)
    meta = {"repo_license": gh.repo(repo)["license"]}
    allowed_here = set(pack["license"].split()[::2])
    files, notes = [], {}
    for item, path in pack["items"].items():
        candidate = Candidate(item, repo, commit, date, path, gh.tree(repo, commit, path), author=pack["vendor"], meta=meta)
        try:
            entry, item_notes = convert(gh, candidate, ["productivity"])
        except Skip as skip:
            raise SystemExit(f"{folder.name}/{item}: {skip}")
        if entry["name"] != item:
            raise SystemExit(f"{folder.name}/{item}: listed as {entry['name']} by its front matter; name the item so")
        if not set(entry["license"].split()[::2]) <= allowed_here:
            raise SystemExit(f"{folder.name}/{item}: {entry['license']} is not within the pack's {pack['license']}")
        files += entry["upstream"]["files"]
        notes[item] = item_notes
    if len(files) > MAX_FILES:
        raise SystemExit(f"{folder.name}: {len(files)} files; one upstream pins at most {MAX_FILES}: split the pack")
    pins = {"repo": repo, "commit": commit, "files": sorted(files, key=lambda f: f["to"]), "notes": notes}
    (folder / "pins.json").write_text(json.dumps(pins, indent=2, ensure_ascii=False) + "\n")
    print(f"{folder.name}: {len(pack['items'])} skills, {len(files)} files at {repo}@{commit[:7]}", file=sys.stderr)


def run_mirror(gh, cfg, args):
    args = argparse.Namespace(**vars(args))
    for key in ("match", "offset", "limit"):
        if key in cfg and getattr(args, key) in (None, 0):
            setattr(args, key, re.compile(cfg[key], re.I) if key == "match" else cfg[key])
    out_dir = pathlib.Path(args.out) if args.out else ROOT / "dist" / "mirrors" / cfg["name"]
    old = out_dir / "index.json"
    previous = json.loads(old.read_text()) if old.is_file() else {}
    run = Run(previous)
    KINDS[cfg["kind"]](gh, cfg, args, run)
    text = report(cfg["name"], cfg, run, args)
    if args.dry_run:
        print(text)
        return run
    data = build_index(run, previous, datetime.now(timezone.utc))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_bytes(data)
    (out_dir / "report.md").write_text(text + "\n")
    print(f"{cfg['name']}: taken {len(run.taken)}, skipped {len(run.skipped)}, "
          f"flagged {sum(1 for t in run.taken if flagged_notes(t[2]))}, into {out_dir}", file=sys.stderr)
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], usage=__doc__.split("\n\n")[1])
    parser.add_argument("name", nargs="?")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--match")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-gh", action="store_true")
    parser.add_argument("--survey", action="store_true")
    parser.add_argument("--pin", nargs="*")
    parser.add_argument("--bump", action="store_true")
    args = parser.parse_args()
    mirrors = load_config()
    if args.pin is not None:
        folders = [PINNED / name for name in args.pin] or sorted(f.parent for f in PINNED.glob("*/pack.yml"))
        gh = GitHub(use_gh=not args.no_gh)
        for folder in folders:
            pin(gh, folder, args.bump)
        print(f"GitHub API requests: {gh.calls} ({'gh' if gh.gh else 'https'})", file=sys.stderr)
        return
    if args.list:
        for m in mirrors:
            print(f"{m['name']:28} {m['kind']:20} {m.get('repo') or m.get('url')}{'  (manual)' if m.get('manual') else ''}")
        return
    if (args.limit is not None and args.limit < 1) or args.offset < 0:
        raise SystemExit("--limit is at least 1 and --offset at least 0")
    args.match = re.compile(args.match, re.I) if args.match else None
    if args.all == bool(args.name):
        raise SystemExit("name one mirror, or --all")
    chosen = [m for m in mirrors if not m.get("manual")] if args.all else [m for m in mirrors if m["name"] == args.name]
    if not chosen:
        raise SystemExit(f"no mirror {args.name} in mirrors.yml (scripts/mirror.py --list)")
    if args.out and len(chosen) > 1:
        raise SystemExit("--out takes one mirror")
    if args.survey:
        if len(chosen) != 1 or chosen[0]["kind"] != "hermes-index":
            raise SystemExit("--survey takes one hermes-index mirror")
        return hermes_survey(chosen[0], args)
    gh = GitHub(use_gh=not args.no_gh)
    for cfg in chosen:
        run_mirror(gh, cfg, args)
    print(f"GitHub API requests: {gh.calls} ({'gh' if gh.gh else 'https'})", file=sys.stderr)


if __name__ == "__main__":
    main()
