#!/usr/bin/env python3
"""Writes site/index.json from every plugin's plugin.yml and the packages of its release,
and signs it. Run by a maintainer on their own machine: the signing key stays in their
keychain and never reaches GitHub.

    scripts/publish.py            packages from each plugin's GitHub release
    scripts/publish.py --local    packages from dist/, for a dry run

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

import yaml

REPO = "DroBov1Tya/duskcode-plugins"
KEYCHAIN_SERVICE = "duskcode-plugins-signing"
KEYCHAIN_ACCOUNT = "ed25519"
ROOT = pathlib.Path(__file__).resolve().parent.parent
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


def entry(manifest_file, local):
    manifest = yaml.safe_load(manifest_file.read_text())
    name, version = manifest["name"], str(manifest["version"])
    return {
        "name": name,
        "version": version,
        "description": manifest.get("description", ""),
        "platforms": manifest.get("platforms", []),
        "clients": manifest.get("clients", []),
        "permissions": manifest.get("permissions", {}),
        "homepage": f"https://github.com/{REPO}/tree/main/plugins/{name}",
        "downloads": packages(name, version, local),
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
    plugins = [entry(file, local) for file in sorted(ROOT.glob("plugins/*/plugin.yml"))]
    index = {"format": 1, "plugins": plugins}
    data = (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode()
    (ROOT / "site" / "index.json").write_bytes(data)
    (ROOT / "site" / "index.json.sig").write_bytes(sign(data))
    print(f"signed {len(plugins)} plugins into site/index.json")


if __name__ == "__main__":
    main()
