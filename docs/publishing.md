# Publishing to the Workshop

A contribution is a pull request. The maintainer reviews it, builds it, and signs the
next list; nothing reaches users before that.

## Every item

- Your own work, or work whose license lets it be redistributed here. Keep the license
  text (`LICENSE`, or `LICENSE-*.txt`) and any `NOTICE` of the upstream in the item's
  folder, name the upstream and say what you changed in a `NOTICE.md`.
- Add it to `catalog.yml`: a `category` and up to 8 `tags`, each `a-z`, `0-9` and `-`.
- Names are `a-z`, `0-9`, `-` (and `_` in a plugin's), starting with a letter or digit.
- No secrets, no binaries in a pack, no symlinks. A pack is plain files only; at most 4000
  files and 256 MiB unpacked, and a package of at most 64 MiB.
- Skills and agents are text the model reads: they must not tell it to hide what it does,
  bypass the user's approvals or send data out. Content in them is reviewed as code.

## A cover

- Original artwork only: no logo, mark or trade dress of anybody else. A vendor's name
  may appear as text. A pack of a vendor's skills is not endorsed by that vendor.
- `covers/<name>.webp` or `.png`, at most 512 KiB, 1200x630. Keep the Workshop look: dark
  background, one accent colour, geometric shapes, the name as large text.
- Keep the source as `covers/src/<name>.svg` with generic fonts only (no font files).
  `scripts/make-covers.py` and `scripts/render-covers.sh` show how the existing ones are made.

## A plugin

`plugins/<name>/plugin.yml` and the program. Permissions are asked for exactly and
shown to the user before install. A plugin may be written in any language: ship packages
per `os` and `arch` for a compiled program (`scripts/package.sh`), or one package for a
script and name the interpreter it needs in the description, since duskcode never installs
one. It runs as a separate process, in duskcode's sandbox.

## A skill

A folder with `SKILL.md`: front matter `name` and `description`, and for others' work
`source`, `author`, `license`, `upstream` and `changes`. Executable helpers are not
accepted in a pack: keep the workflow in Markdown.

## A pack

`packs/<pack>/pack.yml`:

```yaml
name: my-pack              # a-z, 0-9, -
title: "My Pack"
description: "One sentence."
vendor: someone
kind: skills               # or agents
items: [one, two]          # exactly the folders next to pack.yml
license: MIT               # SPDX; the items' own licenses stay in their folders
upstream: https://...      # optional: where a vendor's skills come from
```

Each item is a folder next to `pack.yml`. `scripts/package-packs.sh <pack> <version>`
builds `dist/<pack>-<version>.tar.gz` deterministically.

## A mirror

Run your own signed list (`index.json` and `index.json.sig`, format 2, Ed25519), publish
it over https, and tell users its address and public key; they add it to `config.yml`
as Community. To be Verified, ask the maintainer to add `{name, url, key}` to
`verified.yml` after checking you.
