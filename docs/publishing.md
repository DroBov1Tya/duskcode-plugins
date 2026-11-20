# Publishing to the Workshop

A contribution is a pull request. The maintainer reviews it, builds it, and signs the
next list; nothing reaches users before that.

## Every item

- Your own work, or work whose license lets it be redistributed here. Keep the license
  text (`LICENSE`, or `LICENSE-*.txt`) and any `NOTICE` of the upstream in the item's
  folder, name the upstream and say what you changed in a `NOTICE.md`.
- Add it to `catalog.yml`: 1 to 3 `categories` from the fixed list (`coding`, `review`,
  `testing`, `security`, `research`, `writing`, `data`, `devops`, `design`,
  `productivity`, `devices`, `communication`) and up to 8 `tags`, each `a-z`, `0-9` and `-`.
- Every item names its `author` (shown as "by X"), its `license` (an SPDX id, the one in
  the upstream's own LICENSE file) and its `source` (an https address). A pack has them in
  `pack.yml` as `vendor`, `license` and `upstream`; a plugin has them in `catalog.yml`.
- `scripts/check-index.py --repo .` checks all of this and must pass.
- Names are `a-z`, `0-9`, `-` (and `_` in a plugin's), starting with a letter or digit.
- No secrets, no binaries in a pack, no symlinks. A pack is plain files only; at most 4000
  files and 256 MiB unpacked, and a package of at most 64 MiB.
- Skills and agents are text the model reads: they must not tell it to hide what it does,
  bypass the user's approvals or send data out. Content in them is reviewed as code.

## Official and Verified, and other people's names

- The **Official** badge is for work by the Workshop's owner (duskcode). Anything written
  by somebody else, a company's published skills included, is **Verified**: checked and
  signed here, not ours. The badge follows from the author; no file sets it, and
  `scripts/check-index.py` refuses a list that says otherwise.
- An item's name, title and cover never carry a company's name (Anthropic, OpenAI, NVIDIA
  and the like) and never suggest that the company made, backs or runs the item here.
  Name it for what it does: "GPU Computing Skills" or "Web Builder Skills", not
  "<Company> Skills" or "Skills for <product>".
- The company is named where it is a fact the license asks for: in `vendor` / `author`,
  in `upstream` / `source`, in the license and notice files, and once in the description
  ("written by X"). A product's name (Claude, GPT, CUDA) may appear in a description, where
  it says what the item works with; never in a title or a cover.
- A connector is the exception for names: it is named for the service it connects to,
  and its description says it is that service's own server. Its cover still names what
  the service is for, never the service ([connectors.md](connectors.md)).
- The description of somebody else's work ends with "Not affiliated with or endorsed by
  <author>."
- No license, or one that does not allow copying (anything outside MIT, Apache-2.0,
  BSD-2-Clause, BSD-3-Clause, ISC, 0BSD, MPL-2.0, CC-BY-4.0, CC0-1.0, Unlicense): the
  content is not copied here. Link to it instead.

[third-party.md](third-party.md) lists what each pack from an upstream owes its license.

## A cover

- Original artwork only: no logo, mark, name, colours or trade dress of anybody else, as
  a picture or as text.
- `covers/<name>.webp` or `.png`, at most 512 KiB, 1200x630 (2400x1260 at most; the header is checked). Keep the Workshop look: dark
  background, one accent colour, geometric shapes, the name as large text.
- One ratio, 40:21 (1200x630), everywhere a cover is drawn, in the app and on the site.
  The picture is cropped to fill that frame, never stretched, so a cover of another shape
  loses its edges.
- Keep the name and the drawing at least 24 px (at 1200 wide) from every edge: the frame's
  corners are rounded and a frame a pixel off the ratio crops a little.
- An item without `covers/<name>.*` is listed without a cover. Where there is none, or it
  cannot be fetched or fails its checks, duskcode and the site draw a plain placeholder
  with the item's kind instead.
- Keep the source as `covers/src/<name>.svg` with generic fonts only (no font files).
  `scripts/make-covers.py` and `scripts/render-covers.sh` show how the existing ones are made.

## Screenshots

Optional, and shown as a gallery with the item's details, in the order listed.

- Up to 8 per item, in `screenshots/<item>/`, each a `.png` or `.webp` of at most 1 MiB
  whose bytes are that format (duskcode checks the first bytes, not only the name).
- 16:10, at most 3200x2000 pixels; 1600x1000 is recommended. The gallery's frame is 16:10
  and fits a shot whole, so a shot of another shape (16:9 included) gets bars at its sides
  or above and below; it is never cropped or stretched. WebP keeps a shot of an interface
  well under the limit.
- List them in `catalog.yml` with a short caption (one line, at most 120 characters, no
  control characters):

  ```yaml
  my-pack:
    categories: [coding, testing]
    tags: [tdd]
    screenshots:
      - {file: 1-overview.webp, caption: "The list of skills"}
  ```

- Show the item itself: its own interface or its own files. No secrets, tokens, real
  names, addresses or other personal data anywhere in a shot, including window titles,
  paths and terminal prompts. No trademarks or interfaces of other vendors beyond what
  the item's own UI shows.
- `scripts/publish.py` checks each one as duskcode does, copies it to
  `site/screenshots/<item>/` and names its size and SHA-256 in the signed list;
  `scripts/check-index.py` checks the list's screenshots again. The text screenshots of
  the duskcode packs are rendered from their files by `scripts/render-screenshots.py`.

## Stars

The official list carries no `stars`. The only count it could give was a GitHub
repository's: this repository's for duskcode's own items, a vendor's whole repository for a
vendor's pack. Neither is a count of the item, so it was a placeholder, and duskcode drops
the stars of an official or a verified listing whatever a list says. `scripts/publish.py`
writes none and `scripts/check-index.py` refuses a list that has them.

A mirror's list may carry `stars`: the star count of the GitHub repository its `homepage`
names. duskcode shows it only for a mirror the user added, only when `homepage` is a
`https://github.com/owner/name` page, and only as "N GitHub stars of owner/name" on the
item's page: never as a rating, never on a card, and nothing is sorted or ranked by it.

## A plugin

`plugins/<name>/plugin.yml` and the program. Permissions are asked for exactly and
shown to the user before install. A plugin may be written in any language: ship packages
per `os` and `arch` for a compiled program (`scripts/package.sh`), or one package for a
script and name the interpreter it needs in the description, since duskcode never installs
one. It runs as a separate process, in duskcode's sandbox.

## A skill

A folder with `SKILL.md`: front matter `name` (the folder's) and `description`, and for
others' work `source`, `author`, `license`, `upstream` and `changes`, unless the upstream
file is kept byte for byte; then its `NOTICE.md` says so. Executable helpers and binary
files are not accepted in a pack: keep the workflow in Markdown.

## A pack

`packs/<pack>/pack.yml`:

```yaml
name: my-pack              # a-z, 0-9, -
title: "My Pack"
description: "One sentence."
vendor: someone            # the author, shown as "by someone"
kind: skills               # or agents
items: [one, two]          # exactly the folders next to pack.yml
license: MIT               # SPDX; the items' own licenses stay in their folders
upstream: https://...      # only for work that came from somewhere else: its source
```

These eight fields and no others: duskcode refuses a pack.yml with a field it does not
know. A pack with `upstream` keeps a `LICENSE*` and a `NOTICE.md` in every item folder
(nothing but item folders may sit beside `pack.yml`).

Each item is a folder next to `pack.yml`. `scripts/package-packs.sh <pack> <version>`
builds `dist/<pack>-<version>.tar.gz` deterministically.

## A mirror

[external-repositories.md](external-repositories.md) has the full requirements. In short:
run your own signed list (`index.json` and `index.json.sig`, format 2, Ed25519), publish
it over https, and tell users its address and public key; they add it to `config.yml`
as Community. To be Verified, ask the maintainer to add `{name, url, key}` to
`verified.yml` after checking you.
