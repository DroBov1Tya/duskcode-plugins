#!/bin/sh
# Renders covers/src/*.svg to covers/<name>.webp (1200x630, at most 512 KiB), the format
# the store takes. Needs rsvg-convert and cwebp.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
for svg in "$here"/covers/src/*.svg; do
  name=$(basename "$svg" .svg)
  rsvg-convert -w 1200 -h 630 -o "$tmp/$name.png" "$svg"
  cwebp -quiet -q 90 "$tmp/$name.png" -o "$here/covers/$name.webp"
  size=$(wc -c < "$here/covers/$name.webp")
  [ "$size" -le 524288 ] || { echo "$name.webp is $size bytes, over 512 KiB" >&2; exit 1; }
  echo "$name.webp $size"
done
