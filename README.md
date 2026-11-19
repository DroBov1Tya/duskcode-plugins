# Duskcode Workshop

The Workshop of [Dusk Code](https://github.com/DroBov1Tya/dusk_code), the open-source
coding agent in Rust: plugins, skills, skill packs and agents, each with its own cover,
their signed packages and the [Workshop page](https://drobov1tya.github.io/duskcode-workshop/).
In the app they are under Plugins, Workshop, one click to install.

[Dusk Code](https://github.com/DroBov1Tya/dusk_code) ·
[Site](https://drobov1tya.github.io/dusk_code/) ·
[Workshop](https://drobov1tya.github.io/duskcode-workshop/) ·
[Writing a plugin](https://github.com/DroBov1Tya/dusk_code/blob/main/docs/plugins.md) ·
[Publishing here](docs/publishing.md)

(The repository was `duskcode-plugins` until 2026-11-18. GitHub redirects the old repository
address; the old page address no longer answers.)

## What it holds

```
plugins/<name>/                 a plugin: plugin.yml, its source, icons
packs/<pack>/pack.yml           a pack: name, title, description, vendor, kind, items, license
packs/<pack>/<item>/            each item: a skill folder (SKILL.md, LICENSE, NOTICE) or an agent folder
covers/<name>.webp              the card picture of each plugin and pack (at most 512 KiB)
covers/src/<name>.svg           its source; scripts/make-covers.py writes them, render-covers.sh renders
screenshots/<name>/             optional demo pictures of an item (up to 8, at most 1 MiB each)
catalog.yml                     categories, tags and screenshots of each item; a plugin's author, license, source
verified.yml                    mirrors the maintainer vouches for
mirrors.yml                     outside skill catalogues scripts/mirror.py turns into unsigned lists
scripts/                        package.sh, package-packs.sh, publish.py, check-index.py (a list, or --repo a repository), mirror.py
site/                           the page and the signed list (index.json, index.json.sig, covers/, screenshots/)
```

| Pack | Kind | Badge | Author | License |
| --- | --- | --- | --- | --- |
| [duskcode-engineering](packs/duskcode-engineering) | skills | Official | duskcode | MIT |
| [duskcode-security](packs/duskcode-security) | skills | Official | duskcode | MIT |
| [duskcode-agents](packs/duskcode-agents) | agents | Official | duskcode | MIT |
| [web-builder-skills](packs/web-builder-skills) | skills | Verified | Anthropic ([source](https://github.com/anthropics/skills)) | Apache-2.0 |
| [dev-workflow-skills](packs/dev-workflow-skills) | skills | Verified | OpenAI ([source](https://github.com/openai/skills)) | Apache-2.0 |
| [gpu-computing-skills](packs/gpu-computing-skills) | skills | Verified | NVIDIA ([source](https://github.com/NVIDIA/skills)) | CC-BY-4.0 AND Apache-2.0 |

`duskcode-agents` holds every agent of duskcode, including those it also builds in.
Official is duskcode's own work; Verified is somebody else's, checked and signed here.
Those packs keep their license and notice files and name their changes
([docs/third-party.md](docs/third-party.md)); duskcode is not affiliated with or endorsed
by their authors, and their names are used only to say who wrote the work.

| Plugin | What it does | Systems |
| --- | --- | --- |
| [ios-simulator](plugins/ios-simulator) | Xcode's iOS Simulator in a panel, and a tool for the agent to use it | macOS |
| [telegram](plugins/telegram) | Talk to duskcode from Telegram: messages, answers, questions and approvals | macOS |
| [vphone](plugins/vphone) | A vphone virtual iPhone in a panel, and a tool for the agent to use it | macOS |

`crates/phone-kit` is shared by ios-simulator and vphone: the phone panel and the MCP
tool over one `Phone` trait.

## Tiers

A tier is about the list an item came from; the Official and Verified badges above are
about who wrote an item of this list.

- **Official**: what this repository's list offers, signed by the store's Ed25519 key
  that is built into duskcode. A contribution becomes Official when a pull request is
  reviewed and merged, and the maintainer builds it and signs the next list.
- **Verified**: a mirror somebody else runs. It publishes its own `index.json` and
  `index.json.sig`, signed with its own Ed25519 key. The maintainer checks it and adds its
  `name`, `url` and `key` to `verified.yml`; the next signed official list carries them, and
  duskcode shows a mirror a user added with exactly that address and key as Verified.
- **Community**: any mirror a user adds in `config.yml` with its key. Nobody vouches for it.
- **Unverified**: a list a user adds without a key. Only skills and packs pinned to a
  commit of their author's GitHub repository are taken from it, as text.
  `scripts/mirror.py` writes such lists from outside catalogues (a GitHub repository of
  skills, a Claude Code marketplace, Hermes Agent's index); see [docs/mirrors.md](docs/mirrors.md).

## How an item gets to a user

1. A plugin lives in `plugins/<name>/` (see
   [Writing a plugin](https://github.com/DroBov1Tya/dusk_code/blob/main/docs/plugins.md)).
   A pack lives in `packs/<pack>/`. Both need a cover and an entry in `catalog.yml`.
2. A tag `<name>-v<version>` builds a plugin for each system in its `platforms`, or a
   pack with `scripts/package-packs.sh`, attests where each package was built and uploads
   it to that tag's release. The build job holds no write token. A pack's version is
   `1.<date of its last commit>.0`.
3. A maintainer runs `scripts/publish.py` on their own machine. It keeps every version
   already signed as it was signed; for a new version it checks the build attestations and
   asks before signing the hashes it shows. It writes `site/index.json` (format 2: kind,
   category, tags, cover, screenshots, created, updated, verified; no stars) with the next serial and an
   expiry (180 days) and signs it with the key from their keychain into
   `site/index.json.sig`. The key never reaches GitHub. `scripts/publish.py --dry-run`
   writes the unsigned list to a temp folder for review and signs nothing;
   `scripts/check-index.py <index.json>` checks it against duskcode's format 2 rules.
4. A push of `site/` puts the page and the signed list on GitHub Pages.

duskcode installs a plugin only when the list's signature checks against the key built
into it, the package has the size and hash the list names, it unpacks to plain files
inside its own folder, and its `plugin.yml` asks for exactly the permissions the list
showed the user.

## Trying it locally

```sh
cargo build --release -p telegram
mkdir -p target/aarch64-apple-darwin/release && cp target/release/telegram target/aarch64-apple-darwin/release/
sh scripts/package.sh telegram aarch64-apple-darwin
scripts/publish.py --local     # into dist/, signed with the key in your keychain
```

MIT.
