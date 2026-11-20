#!/usr/bin/env python3
"""Writes site/index.json from every plugin's plugin.yml and the packages of its release,
and signs it. Run by a maintainer on their own machine: the signing key stays in their
keychain and never reaches GitHub.

    scripts/publish.py            packages from each plugin's GitHub release
    scripts/publish.py --local    packages from dist/, into dist/, signed with the key
    scripts/publish.py --dry-run  unsigned list into a temp folder for review: builds the
                                  packs, asks nothing, never touches the key
    scripts/publish.py --format=3 also writes each item's author, license, source,
                                  categories and badge, and for a plugin the mcp,
                                  programs and skills its plugin.yml brings; only once
                                  the duskcode in use reads format 3, since an older one
                                  refuses the list. Only format 3 carries the packs of
                                  pinned/, pinned to a commit of their author's
                                  repository with the SHA-256 of every file
                                  (pins.json, from scripts/mirror.py --pin)

The repository is checked first (scripts/repo.py), and nothing is written when it fails.
Another repository laid out the same way publishes its own list with WORKSHOP_REPO set to
its `owner/name` (docs/external-repositories.md).

A version already in the signed list keeps the packages it was signed with, whatever its
release holds now, so a release changed on GitHub is never signed again. A new version's
packages must carry a build attestation from this repository's release workflow, and
their hashes are shown for a yes before they are signed. Every list gets the next serial
and an expiry, so duskcode refuses an older or a stale list.

The list is format 2: plugins and packs, each with kind, category (the first of its
categories), tags, a cover when covers/ has one (copied to site/covers/), screenshots (from screenshots/<name>/, copied to site/screenshots/<name>/
in catalog.yml's order) and created/updated dates from git. It writes no stars: this is
the official list, and a count of this repository's or a vendor's whole repository's
stars is not the item's, so duskcode drops it anyway. A pack is built by
scripts/package-packs.sh; its version is 1.<date of its last commit>.0.

A connector (connectors/<name>/connector.yml) has no package: its entry carries the
`server` that duskcode adds to the user's connectors, the address or the pinned npx/uvx
package, how it signs in and the names of the secrets the user fills in. A duskcode
before connectors leaves such an entry out of the list and reads the rest.

A plugin's release is tagged <name>-v<version>; its packages are named
<name>-<version>-<os>-<arch>.tar.gz by scripts/package.sh.
"""

import base64
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import yaml

import pictures
import pinned
import repo

REPO = os.environ.get("WORKSHOP_REPO", "DroBov1Tya/duskcode-workshop")
KEYCHAIN_SERVICE = "duskcode-plugins-signing"
KEYCHAIN_ACCOUNT = "ed25519"
ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = f"{REPO}/.github/workflows/release.yml"
# A list lives this long; publish again before then.
LIFETIME = timedelta(days=180)
CATALOG = yaml.safe_load((ROOT / "catalog.yml").read_text())
VERIFIED = yaml.safe_load((ROOT / "verified.yml").read_text()) or []
# 3 adds who made each item; an older duskcode refuses a format 3 list whole.
FORMAT = 3 if "--format=3" in sys.argv[1:] else 2
PACKAGE = re.compile(r"^(?P<name>[a-z0-9_-]+)-(?P<version>[^-]+)-(?P<os>macos|linux|windows)-(?P<arch>[a-z0-9_]+)\.tar\.gz$")


def packages(name, version, local):
    tag = f"{name}-v{version}"
    if local:
        folder = ROOT / "dist"
    else:
        folder = pathlib.Path(tempfile.mkdtemp()) / tag
        subprocess.run(
            ["gh", "release", "download", tag, "--repo", REPO, "--pattern", "*.tar.gz", "--dir", str(folder)],
            check=True,
        )
    found = []
    for file in sorted(folder.glob(f"{name}-{version}-*.tar.gz")):
        match = PACKAGE.match(file.name)
        if not match:
            continue
        if not local:
            subprocess.run(
                ["gh", "attestation", "verify", str(file), "--repo", REPO, "--signer-workflow", WORKFLOW],
                check=True, stdout=subprocess.DEVNULL,
            )
        data = file.read_bytes()
        found.append({
            "os": match["os"],
            "arch": match["arch"],
            "url": f"https://github.com/{REPO}/releases/download/{tag}/{file.name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })
    if not found:
        sys.exit(f"no packages for {name} {version}")
    return found


def utc(iso):
    return datetime.fromisoformat(iso).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_dates(folder):
    """First and last commit date of a folder; today for one not committed yet."""
    out = subprocess.run(
        ["git", "log", "--format=%aI", "--", str(folder)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.split()
    if not out:
        now = utc(datetime.now(timezone.utc).isoformat())
        return now, now
    return utc(out[-1]), utc(out[0])


def copy_cover(name, out):
    found = [f for ext in ("webp", "png") if (f := ROOT / "covers" / f"{name}.{ext}").exists()]
    if not found:
        # duskcode and the site draw a plain placeholder for an item without one.
        print(f"{name}: no cover in covers/, listed without one", file=sys.stderr)
        return None
    file = found[0]
    data = file.read_bytes()
    if why := pictures.problem(f"covers/{file.name}", data, pictures.COVER_LIMIT):
        sys.exit(f"covers/{file.name}: {why}")
    (out / "covers").mkdir(parents=True, exist_ok=True)
    (out / "covers" / file.name).write_bytes(data)
    return {"path": f"covers/{file.name}", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def copy_screenshots(name, meta, out):
    """catalog.yml's screenshots of `name`, checked as the core checks them, copied
    beside the list."""
    shots = meta.get("screenshots") or []
    if len(shots) > pictures.MAX_SCREENSHOTS:
        sys.exit(f"{name}: {len(shots)} screenshots, at most {pictures.MAX_SCREENSHOTS}")
    found = []
    for shot in shots:
        if set(shot) - {"file", "caption"} or "/" in shot.get("file", "/"):
            sys.exit(f"{name}: a screenshot is {{file, caption}} with a plain file name: {shot}")
        path = f"screenshots/{name}/{shot['file']}"
        file = ROOT / path
        if not file.is_file() or file.is_symlink():
            sys.exit(f"{path} is not a file")
        data = file.read_bytes()
        if why := pictures.problem(path, data, pictures.SCREENSHOT_LIMIT):
            sys.exit(f"{path}: {why}")
        item = {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        if "caption" in shot:
            if not pictures.caption_ok(shot["caption"]):
                sys.exit(f"{path}: the caption is not one plain line of up to {pictures.MAX_CAPTION} characters")
            item["caption"] = shot["caption"]
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(data)
        found.append(item)
    return found


def extras(name, folder, meta, out, author, license, source, upstream=None):
    """Fields of format 2 shared by plugins and packs, and format 3's when asked for."""
    created, updated = git_dates(folder)
    screenshots = copy_screenshots(name, meta, out)
    cover = copy_cover(name, out)
    credit = {
        "author": author,
        "license": license,
        "source": source,
        "categories": meta["categories"],
        "badge": repo.badge(author, upstream),
    }
    return {
        "category": meta["categories"][0],
        "tags": meta.get("tags", []),
        **({"cover": cover} if cover else {}),
        **({"screenshots": screenshots} if screenshots else {}),
        "created": created,
        "updated": updated,
        **(credit if FORMAT == 3 else {}),
    }


def pack_version(folder):
    return "1." + git_dates(folder)[1][:10].replace("-", "") + ".0"


def pack_download(name, version, local):
    file = f"{name}-{version}.tar.gz"
    tag = f"{name}-v{version}"
    if local:
        subprocess.run([str(ROOT / "scripts" / "package-packs.sh"), name, version], check=True, stdout=subprocess.DEVNULL)
        path = ROOT / "dist" / file
    else:
        folder = pathlib.Path(tempfile.mkdtemp()) / tag
        subprocess.run(
            ["gh", "release", "download", tag, "--repo", REPO, "--pattern", file, "--dir", str(folder)],
            check=True,
        )
        path = folder / file
        subprocess.run(
            ["gh", "attestation", "verify", str(path), "--repo", REPO, "--signer-workflow", WORKFLOW],
            check=True, stdout=subprocess.DEVNULL,
        )
    data = path.read_bytes()
    return {
        "os": "any",
        "arch": "any",
        "url": f"https://github.com/{REPO}/releases/download/{tag}/{file}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


def pack_entry(file, local, confirm, signed, out):
    manifest = yaml.safe_load(file.read_text())
    name, folder = manifest["name"], file.parent
    version = pack_version(folder)
    before = signed.get(name)
    if before and before["version"] == version:
        downloads = before["downloads"]
    else:
        downloads = [pack_download(name, version, local)]
        for download in downloads:
            print(f"{name} {version}: {download['size']} bytes, sha256 {download['sha256']}")
        if confirm and input(f"sign this package of {name} {version}? [y/N] ").strip().lower() != "y":
            sys.exit("nothing signed")
    return {
        "name": name,
        "version": version,
        "kind": "pack",
        "description": manifest["description"],
        "homepage": f"https://github.com/{REPO}/tree/main/packs/{name}",
        "downloads": downloads,
        "skills": manifest["items"],
        **extras(name, folder, CATALOG["packs"][name], out, manifest["vendor"], manifest["license"],
                 manifest.get("upstream") or f"https://github.com/{REPO}/tree/main/packs/{name}",
                 manifest.get("upstream")),
    }


def pinned_entry(file, out):
    """A pack pinned in its author's repository (pinned/<pack>): no package, but the commit
    and the SHA-256 of every file duskcode fetches from GitHub, from pins.json. Format 3 only."""
    folder = file.parent
    pack, pins = pinned.read(folder)
    upstream = pinned.upstream(pins)
    print(f"{pack['name']}: {len(upstream['files'])} files pinned at {upstream['repo']}@{upstream['commit'][:7]}")
    return {
        "name": pack["name"],
        "version": pack_version(folder),
        "kind": "pack",
        "description": pack["description"],
        "homepage": pinned.source(pack),
        "skills": list(pack["items"]),
        "upstream": upstream,
        **extras(pack["name"], folder, CATALOG["packs"][pack["name"]], out, pack["vendor"], pack["license"],
                 pinned.source(pack), pinned.source(pack)),
    }


def entry(manifest_file, local, signed, confirm, out):
    manifest = yaml.safe_load(manifest_file.read_text())
    name, version = manifest["name"], str(manifest["version"])
    before = signed.get(name)
    if before and before["version"] == version:
        downloads = before["downloads"]
    else:
        downloads = packages(name, version, local or not confirm)
        for download in downloads:
            print(f"{name} {version} {download['os']}-{download['arch']}: {download['size']} bytes, sha256 {download['sha256']}")
        if confirm and input(f"sign these packages of {name} {version}? [y/N] ").strip().lower() != "y":
            sys.exit("nothing signed")
    providers = sorted(p["base_url"] for p in (manifest.get("providers") or {}).values())
    meta = CATALOG["plugins"][name]
    return {
        "name": name,
        "version": version,
        "kind": "plugin",
        "description": manifest.get("description", ""),
        "platforms": manifest.get("platforms", []),
        "clients": manifest.get("clients", []),
        "permissions": manifest.get("permissions", {}),
        "homepage": f"https://github.com/{REPO}/tree/main/plugins/{name}",
        "providers": providers,
        "downloads": downloads,
        **extras(name, manifest_file.parent, meta, out, meta["author"], meta["license"], meta["source"]),
        **(repo.brings(manifest_file.parent, manifest) if FORMAT == 3 else {}),
    }


def connector_entry(file, out):
    doc = yaml.safe_load(file.read_text())
    name = doc["name"]
    meta = CATALOG["connectors"][name]
    server = doc["server"]
    return {
        "name": name,
        "version": str(doc["version"]),
        "kind": "connector",
        "description": doc["description"],
        **({"homepage": server["docs"]} if server.get("docs") else {}),
        "server": server,
        **extras(name, file.parent, meta, out, meta["author"], meta["license"], meta["source"]),
    }


def sign(data):
    key = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    old = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory() as folder:
            pem = pathlib.Path(folder) / "key.pem"
            message = pathlib.Path(folder) / "index.json"
            pem.write_bytes(base64.b64decode(key))
            message.write_bytes(data)
            signature = subprocess.run(
                ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(pem), "-in", str(message)],
                check=True, capture_output=True,
            ).stdout
    finally:
        os.umask(old)
    return base64.b64encode(signature) + b"\n"


def main():
    args = sys.argv[1:]
    dry, local = "--dry-run" in args, "--local" in args
    out = pathlib.Path(tempfile.mkdtemp(prefix="workshop-index-")) if dry else ROOT / ("dist" if local else "site")
    found, _ = repo.problems(ROOT)
    if found:
        sys.exit("\n".join(found))
    out.mkdir(exist_ok=True)
    # A real run asks before signing new packages; a local or dry run asks nothing.
    confirm = not (dry or local)
    old = json.loads((ROOT / "site" / "index.json").read_text()) if (ROOT / "site" / "index.json").exists() else {}
    signed = {item["name"]: item for item in old.get("plugins", [])}
    plugins = [entry(f, local, signed, confirm, out) for f in sorted(ROOT.glob("plugins/*/plugin.yml"))]
    plugins += [pack_entry(f, local or dry, confirm, signed, out) for f in sorted(ROOT.glob("packs/*/pack.yml"))]
    held = sorted(ROOT.glob("pinned/*/pack.yml"))
    if FORMAT == 3:
        plugins += [pinned_entry(f, out) for f in held]
    elif held:
        print(f"{len(held)} pinned packs left out: only a format 3 list (--format=3) can name upstream files",
              file=sys.stderr)
    plugins += [connector_entry(f, out) for f in sorted(ROOT.glob("connectors/*/connector.yml"))]
    expires = (datetime.now(timezone.utc) + LIFETIME).replace(microsecond=0)
    index = {
        "format": FORMAT,
        "serial": old.get("serial", 0) + 1,
        "expires": expires.isoformat().replace("+00:00", "Z"),
        "plugins": plugins,
        "verified": VERIFIED,
    }
    data = (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode()
    (out / "index.json").write_bytes(data)
    if dry:
        print(f"dry run: {len(plugins)} entries, unsigned, in {out}/index.json")
        return
    (out / "index.json.sig").write_bytes(sign(data))
    print(f"signed {len(plugins)} entries into {out.name}/index.json, serial {index['serial']}")


if __name__ == "__main__":
    main()
