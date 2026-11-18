#!/usr/bin/env python3
"""Writes site/index.json from every plugin's plugin.yml and the packages of its release,
and signs it. Run by a maintainer on their own machine: the signing key stays in their
keychain and never reaches GitHub.

    scripts/publish.py            packages from each plugin's GitHub release
    scripts/publish.py --local    packages from dist/, into dist/, signed with the key
    scripts/publish.py --dry-run  unsigned list into a temp folder for review: builds the
                                  packs, asks nothing, never touches the key

A version already in the signed list keeps the packages it was signed with, whatever its
release holds now, so a release changed on GitHub is never signed again. A new version's
packages must carry a build attestation from this repository's release workflow, and
their hashes are shown for a yes before they are signed. Every list gets the next serial
and an expiry, so duskcode refuses an older or a stale list.

The list is format 2: plugins and packs, each with kind, category, tags, a cover (copied
to site/covers/), screenshots (from screenshots/<name>/, copied to site/screenshots/<name>/
in catalog.yml's order), stars (counted here from the GitHub API, 0 with a warning when it
cannot be reached) and created/updated dates from git. A pack is built by
scripts/package-packs.sh; its version is 1.<date of its last commit>.0.

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
import urllib.request
from datetime import datetime, timedelta, timezone

import yaml

import pictures

REPO = "DroBov1Tya/duskcode-workshop"
KEYCHAIN_SERVICE = "duskcode-plugins-signing"
KEYCHAIN_ACCOUNT = "ed25519"
ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = f"{REPO}/.github/workflows/release.yml"
# A list lives this long; publish again before then.
LIFETIME = timedelta(days=180)
CATALOG = yaml.safe_load((ROOT / "catalog.yml").read_text())
VERIFIED = yaml.safe_load((ROOT / "verified.yml").read_text()) or []
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


def stars(repo):
    """Stars of a public repository; 0 with a warning when GitHub cannot be asked."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "workshop-publisher"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            return int(json.load(reply)["stargazers_count"])
    except Exception as error:
        print(f"warning: stars of {repo} not read ({error}); using 0", file=sys.stderr)
        return 0


def copy_cover(name, out):
    found = [f for ext in ("webp", "png") if (f := ROOT / "covers" / f"{name}.{ext}").exists()]
    if not found:
        sys.exit(f"no cover for {name}: covers/{name}.webp or .png")
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


def extras(name, folder, meta, out, own_repo=REPO):
    """Fields of format 2 shared by plugins and packs."""
    created, updated = git_dates(folder)
    screenshots = copy_screenshots(name, meta, out)
    return {
        "category": meta["category"],
        "tags": meta["tags"],
        "cover": copy_cover(name, out),
        **({"screenshots": screenshots} if screenshots else {}),
        "stars": stars(meta.get("stars_repo", own_repo)),
        "created": created,
        "updated": updated,
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
        **extras(name, folder, CATALOG["packs"][name], out),
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
        **extras(name, manifest_file.parent, CATALOG["plugins"][name], out),
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
    out.mkdir(exist_ok=True)
    # A real run asks before signing new packages; a local or dry run asks nothing.
    confirm = not (dry or local)
    old = json.loads((ROOT / "site" / "index.json").read_text()) if (ROOT / "site" / "index.json").exists() else {}
    signed = {item["name"]: item for item in old.get("plugins", [])}
    plugins = [entry(f, local, signed, confirm, out) for f in sorted(ROOT.glob("plugins/*/plugin.yml"))]
    plugins += [pack_entry(f, local or dry, confirm, signed, out) for f in sorted(ROOT.glob("packs/*/pack.yml"))]
    expires = (datetime.now(timezone.utc) + LIFETIME).replace(microsecond=0)
    index = {
        "format": 2,
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
