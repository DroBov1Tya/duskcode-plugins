#!/usr/bin/env python3
"""Writes site/index.json from every plugin's plugin.yml and the packages of its release,
and signs it. Run by a maintainer on their own machine: the signing key stays in their
keychain and never reaches GitHub.

    scripts/publish.py            packages from each plugin's GitHub release
    scripts/publish.py --local    packages from dist/, into dist/, for a dry run

A version already in the signed list keeps the packages it was signed with, whatever its
release holds now, so a release changed on GitHub is never signed again. A new version's
packages must carry a build attestation from this repository's release workflow, and
their hashes are shown for a yes before they are signed. Every list gets the next serial
and an expiry, so duskcode refuses an older or a stale list.

A plugin's release is tagged <name>-v<version>; its packages are named
<name>-<version>-<os>-<arch>.tar.gz by scripts/package.sh.
"""

import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import yaml

REPO = "DroBov1Tya/duskcode-workshop"
KEYCHAIN_SERVICE = "duskcode-plugins-signing"
KEYCHAIN_ACCOUNT = "ed25519"
ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = f"{REPO}/.github/workflows/release.yml"
# A list lives this long; publish again before then.
LIFETIME = timedelta(days=180)
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


def entry(manifest_file, local, signed):
    manifest = yaml.safe_load(manifest_file.read_text())
    name, version = manifest["name"], str(manifest["version"])
    before = signed.get(name)
    if before and before["version"] == version:
        downloads = before["downloads"]
    else:
        downloads = packages(name, version, local)
        for download in downloads:
            print(f"{name} {version} {download['os']}-{download['arch']}: {download['size']} bytes, sha256 {download['sha256']}")
        if not local and input(f"sign these packages of {name} {version}? [y/N] ").strip().lower() != "y":
            sys.exit("nothing signed")
    providers = sorted(p["base_url"] for p in (manifest.get("providers") or {}).values())
    return {
        "name": name,
        "version": version,
        "description": manifest.get("description", ""),
        "platforms": manifest.get("platforms", []),
        "clients": manifest.get("clients", []),
        "permissions": manifest.get("permissions", {}),
        "homepage": f"https://github.com/{REPO}/tree/main/plugins/{name}",
        "providers": providers,
        "downloads": downloads,
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
    local = "--local" in sys.argv[1:]
    out = ROOT / ("dist" if local else "site")
    out.mkdir(exist_ok=True)
    previous = ROOT / "site" / "index.json"
    old = json.loads(previous.read_text()) if previous.exists() else {}
    signed = {item["name"]: item for item in old.get("plugins", [])}
    plugins = [entry(file, local, signed) for file in sorted(ROOT.glob("plugins/*/plugin.yml"))]
    expires = (datetime.now(timezone.utc) + LIFETIME).replace(microsecond=0)
    index = {
        "format": 1,
        "serial": old.get("serial", 0) + 1,
        "expires": expires.isoformat().replace("+00:00", "Z"),
        "plugins": plugins,
    }
    data = (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode()
    (out / "index.json").write_bytes(data)
    (out / "index.json.sig").write_bytes(sign(data))
    print(f"signed {len(plugins)} plugins into {out.name}/index.json, serial {index['serial']}")


if __name__ == "__main__":
    main()
