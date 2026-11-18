# A compatible repository

Anybody can run a Workshop of their own. duskcode reads it as a *mirror*: a signed list at
an https address that a user adds with its key. This page is everything such a repository
must meet. Check it with this repository's script, from a checkout of this repository:

```sh
pip install pyyaml
scripts/check-index.py --repo /path/to/your/repository    # the files, before you build
scripts/check-index.py /path/to/your/site/index.json      # the list you built
```

Both print every problem and exit non-zero when there is one.

## What the user sees

- Your items are **Community**: no key of duskcode vouches for them. Nothing your list or
  your files say changes that: the tier comes from the key that signed the list, and the
  Official and Verified badges of the official list are never read from a mirror's list.
- A mirror becomes **Verified** only when the maintainer of the official Workshop adds its
  exact address and key to `verified.yml` after checking who runs it.
- An item of yours that has the name of another source's item is marked as a clash.

## Layout

```
catalog.yml                 every item, see below
packs/<pack>/pack.yml       a pack of skills or of agents
packs/<pack>/<item>/        one folder per item: SKILL.md or AGENT.md, and its files
plugins/<name>/plugin.yml   a plugin (programs; see duskcode's docs/plugins.md)
covers/<name>.webp|.png     optional card picture
screenshots/<name>/         optional, up to 8 pictures
```

A name that is in `catalog.yml` and not in `packs/` or `plugins/`, or the other way
round, is refused.

## pack.yml

Exactly these fields; duskcode refuses a pack with any other.

| Field | Rule |
| --- | --- |
| `name` | the folder's name: `a-z`, `0-9`, `-`, at most 64 |
| `title`, `description` | one line each, at most 1024 characters, no control characters |
| `vendor` | the author, shown as "by <vendor>" |
| `kind` | `skills` or `agents` |
| `items` | 1 to 256 names, exactly the folders beside `pack.yml`, nothing else beside it |
| `license` | SPDX ids joined by `AND` / `OR`, from: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, 0BSD, MPL-2.0, CC-BY-4.0, CC0-1.0, Unlicense |
| `upstream` | optional; the https address the work came from, when it is not your own |

Each item folder holds `SKILL.md` (or `AGENT.md` for `kind: agents`) whose front matter
has `name`, equal to the folder's name, and a `description`.

A pack with `upstream` is somebody else's work, and then:

- every item folder keeps the upstream's license text as `LICENSE*` and a `NOTICE.md`
  that names the upstream, its copyright holder and what you changed;
- the description contains "Not affiliated with or endorsed by <author>";
- the upstream's license must be one of the list above. Work with no license, or with one
  that does not allow copying, is not copied: link to it instead.

## catalog.yml

```yaml
packs:
  my-pack:
    categories: [coding, testing]   # 1 to 3 of the list below
    tags: [tdd]                     # optional, up to 8, a-z 0-9 -
    screenshots:                    # optional
      - {file: 1-overview.webp, caption: "The list of skills"}
plugins:
  my-plugin:
    author: someone
    license: MIT
    source: https://github.com/someone/my-plugin
    categories: [devices]
```

Categories: `coding`, `review`, `testing`, `security`, `research`, `writing`, `data`,
`devops`, `design`, `productivity`, `devices`, `communication`. A pack takes
`categories`, `tags` and `screenshots` here and nothing else (its author, license and
source are in `pack.yml`); a plugin also takes `author`, `license` and `source`.

## Size caps

| What | Cap |
| --- | --- |
| A pack unpacked | 4000 files, 256 MiB, each file 4 MiB, each path 300 bytes |
| A package (`.tar.gz`) | 64 MiB |
| `pack.yml` | 64 KiB |
| The list / its signature | 4 MiB / 1 KiB |
| A cover | 512 KiB, `.png` or `.webp`, at most 2400x1260 pixels (drawn at 1200x630) |
| A screenshot | 1 MiB, `.png` or `.webp`, at most 3200x2000 pixels, up to 8 per item |
| A caption | one line, 120 characters |
| Tags | 8 per item, 32 characters each |

## What is refused

- A link of any kind, a device or anything else that is not a plain file.
- In a pack: an executable file or a binary file. A pack is text the model reads; a
  program belongs in a plugin, where the user sees and approves its permissions.
- A field the reader does not know, in `pack.yml`, `catalog.yml` or the list.
- A company's name (Anthropic, OpenAI, NVIDIA, Microsoft, Google, Amazon, Apple, Meta) in
  an item's name or title. Name the item for what it does and the company in `vendor`.
- A picture whose bytes are not the PNG or WebP its name says, or over the caps.
- Text that tells the model to hide what it does, to skip the user's approvals or to send
  data out. The script cannot see this; a reviewer of a Verified mirror does, and a user
  of a Community one is on their own, which is what the Community mark says.

## Publishing the list

1. Make an Ed25519 key. Keep the private half off your CI; publish the public half
   (base64 of its 32 bytes) where your users can find it.
2. Build each pack with `scripts/package-packs.sh <pack> <version>` and put the packages
   on https. A package link may redirect at most 3 times, to the same host or to GitHub's
   release hosts; the list and the pictures are fetched without redirects.
3. Write `index.json` (format 2: `format`, `serial`, `expires`, `plugins`; no `verified`
   and no trust of your own to give) and sign its exact bytes into `index.json.sig`
   (base64 of the 64-byte signature). `scripts/publish.py` does this for a repository laid
   out as above, with `WORKSHOP_REPO=owner/name` and the key in the macOS keychain item it
   names; read it before you run it.
4. Each list has a higher `serial` than the last and an `expires` in the future: duskcode
   refuses an older or an expired list.
5. Serve `index.json`, `index.json.sig`, `covers/` and `screenshots/` from one https
   folder. The address has no user, password, query or fragment, and must not resolve to
   a private, loopback or link-local address.

A user then adds, in `config.yml` (at most 16 sources):

```yaml
workshop:
  sources:
    - name: yours            # a-z, 0-9, -; not "official" or "local"
      url: https://example.com/workshop/index.json
      key: BASE64-OF-YOUR-ED25519-PUBLIC-KEY
```

If you change the key, duskcode stops reading the mirror until the user writes the new
one: it never asks whether to trust a new key.
