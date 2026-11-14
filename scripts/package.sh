#!/bin/sh
# Packs a built plugin for the store: its plugin.yml, LICENSE and the program under
# bin/, as dist/<name>-<version>-<os>-<arch>.tar.gz. Plain files only, owned by nobody
# in particular, so the archive is the same wherever it is made.
#   scripts/package.sh telegram aarch64-apple-darwin
set -eu

plugin=$1
target=$2
here=$(cd "$(dirname "$0")/.." && pwd)
folder="$here/plugins/$plugin"
version=$(sed -n 's/^version: *//p' "$folder/plugin.yml")
case $target in
  *-apple-darwin) os=macos ;;
  *-linux-*) os=linux ;;
  *) echo "unknown target $target" >&2; exit 1 ;;
esac
arch=${target%%-*}

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/bin"
cp "$folder/plugin.yml" "$here/LICENSE" "$stage/"
[ -d "$folder/icons" ] && cp -R "$folder/icons" "$stage/"
cp "$here/target/$target/release/$plugin" "$stage/bin/$plugin"
chmod 755 "$stage/bin/$plugin"
chmod 644 "$stage/plugin.yml" "$stage/LICENSE"

mkdir -p "$here/dist"
out="$here/dist/$plugin-$version-$os-$arch.tar.gz"
# No extended attributes or AppleDouble files from macOS tar.
COPYFILE_DISABLE=1 tar --no-xattrs -czf "$out" -C "$stage" . 2>/dev/null \
  || COPYFILE_DISABLE=1 tar -czf "$out" -C "$stage" .
echo "$out"
