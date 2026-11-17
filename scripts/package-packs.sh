#!/bin/sh
# Packs one pack of the Workshop as dist/<pack>-<version>.tar.gz: its pack.yml and item
# folders at the archive root, plain files only. Sorted, with a fixed mtime, owner and
# modes, and an unstamped gzip, so the same pack gives the same bytes anywhere.
#   scripts/package-packs.sh duskcode-security 1.20261117.0
set -eu

pack=$1
version=$2
here=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$here/packs/$pack/pack.yml" ] || { echo "no pack $pack" >&2; exit 1; }
mkdir -p "$here/dist"
python3 -I - "$here/packs/$pack" "$here/dist/$pack-$version.tar.gz" <<'PY'
import gzip, io, os, stat, sys, tarfile

folder, out = sys.argv[1:3]
files = []
for base, dirs, names in os.walk(folder):
    dirs.sort()
    for name in sorted(names):
        path = os.path.join(base, name)
        mode = os.lstat(path).st_mode
        if not stat.S_ISREG(mode):
            sys.exit(f"{path} is not a plain file")
        if name == ".DS_Store":
            continue
        files.append((os.path.relpath(path, folder), path))
files.sort()

raw = io.BytesIO()
with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
    for rel, path in files:
        info = tarfile.TarInfo(rel)
        info.size = os.path.getsize(path)
        info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
        info.mode = 0o644
        with open(path, "rb") as handle:
            tar.addfile(info, handle)
with open(out, "wb") as target:
    with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0, compresslevel=9) as zipped:
        zipped.write(raw.getvalue())
print(out)
PY
