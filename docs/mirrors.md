# Mirrors of outside skill catalogues

`scripts/mirror.py` turns a skill catalogue that is not in Dusk's format into a Dusk list:
a format 3 `index.json` in which every entry is one skill, pinned to a commit of its
author's GitHub repository with the SHA-256 of each of its files. The list is **not
signed**. A user adds it by its address as a source without a key, and Dusk shows what it
offers as **Unverified**.

Dusk installs such a skill straight from GitHub. It fetches exactly the pinned files at the
pinned commit from `raw.githubusercontent.com`, checks each one's size, hash and that it is
text, and writes nothing unless all of them pass (`projects/core/src/plugins/store/upstream.rs`
in the app). The Workshop hosts only the list, never the skills' files.

Nothing here changes the official list or its signature. A mirrored skill moves to the
signed official list only when a maintainer reviews it and packs it, as `web-builder-skills`
was (see [third-party.md](third-party.md)).

## What Unverified means

Dusk reads a source without a key since v0.76.0. See its `docs/plugins.md`, "Sources
without a key", and `projects/core/src/plugins/store/guard.rs`.

- **Nobody vouches for the list.** Dusk does not fetch a `.sig` for it. Every other check
  of a list still applies: https only, public addresses, no redirects, at most 4 MiB and
  2000 entries, format 3, not expired, names, paths and per-file SHA-256.
- **Only pinned text.** Dusk keeps only skills, packs and agents whose files are pinned
  upstream, as UTF-8 text. It drops plugins and packaged downloads, and says so on the
  source's row. It reads no covers, screenshots or stars from the list. The converter
  writes skills only.
- **The serial is not held to.** Anyone who serves an unsigned list can write any serial.
  What protects the user is the commit and the file hashes in the install record.
- **No shadowing.** A name that is, or is one edit away from, one of these is refused as
  taken: a name an Official or Verified listing offers, anything installed from another
  source, a built-in skill, or the `duskcode` pack. The converter already skips Dusk's
  built-in names (`RESERVED` in `scripts/mirror.py`). It cannot know what the user has
  installed or what other lists offer.
- **A review before every install or update.** Dusk shows the files, what changed against
  the copy on disk, the `SKILL.md` diff and the scripts. It says plainly that nobody
  vouches for the item. "Update all" never updates an Unverified item.
- **At runtime.** `load_skill` gives the skill's text after a line saying it comes from an
  unverified source and is third-party data. Its `links:` stay inside its own folder. Its
  scripts are plain text that runs only under the user's permission mode, like any command.
- **Identity.** A listing shows its source, the host of its list and the pinned
  repository. Its `author` is shown as that source's claim.

## Kinds of mirror

| Kind | Reads | Takes |
|---|---|---|
| `skills-repo` | a GitHub repository of `SKILL.md` folders (the [Agent Skills](https://agentskills.io/specification) standard), e.g. `anthropics/skills` | every outermost folder under `path` that holds a `SKILL.md` |
| `claude-marketplace` | a repository with `.claude-plugin/marketplace.json` | only the `skills/` folders of its plugins, or the skill folders a plugin's entry lists. Never MCP servers, hooks, commands, agents or LSP servers. A plugin in another GitHub repository is read at the `sha` the marketplace pins (else its `ref`). `npm`, `archive`, `command` and non-GitHub sources are skipped |
| `hermes-index` | Hermes Agent's skills index (`skills-index.json`, about 45 MB and 104k entries) | each entry resolved to its GitHub folder and pinned to the commit its branch names now. ClawHub and LobeHub entries name no GitHub location, so they cannot be pinned and are skipped |

## Adding a mirror

Add an entry to `mirrors.yml`:

```yaml
mirrors:
  - name: someones-skills        # a-z, 0-9, -; the list's folder name
    kind: skills-repo
    repo: someone/skills         # owner/name on GitHub
    path: skills                 # optional: where the SKILL.md folders are
    ref: main                    # optional: branch, tag or commit; default branch otherwise
    author: Someone              # optional: for skills whose front matter names no author
    categories: [coding]         # optional fallback, 1 to 3 of the fixed list
    match: '^web-'               # optional: the slice taken when the command names none
    limit: 20                    # optional, likewise offset
    manual: false                # true: never run by --all
```

A `hermes-index` mirror names `url` instead of `repo`. Name a mirror for what it holds,
never for whose it is. See "Names" below; the script refuses a mirror name with a company's
word in it.

## Running it

It needs Python 3.9 or newer with PyYAML (`pip install pyyaml`). `gh`, logged in, is
optional but recommended.

```sh
scripts/mirror.py --list                                  # the mirrors of mirrors.yml
scripts/mirror.py --all                                   # the Unverified lists, see below
scripts/mirror.py document-design-dev-skills              # dist/mirrors/document-design-dev-skills/
scripts/mirror.py document-design-dev-skills --dry-run    # the report only, nothing written
scripts/mirror.py plugin-directory-skills --match '^(frontend|security)' --limit 10
scripts/mirror.py skills-hub-index --survey               # what of the index can be converted
scripts/mirror.py skills-hub-index --match '^github/' --limit 50 --out /some/folder
scripts/mirror.py skills-hub-index --match '^skills-sh/' --offset 2000 --limit 2000
scripts/check-index.py --unsigned dist/mirrors/document-design-dev-skills/index.json
scripts/check-index.py --unsigned dist/mirrors/document-design-dev-skills/index.json --fetch pdf docx
```

**The Unverified lists in one command.** `scripts/mirror.py --all` builds every mirror
`mirrors.yml` does not mark `manual`:
- `dist/mirrors/document-design-dev-skills/`: the whole of `anthropics/skills`;
- `dist/mirrors/skills-hub-index/`: the slice `mirrors.yml` names, the first 20 of the
  Hermes index's own `official/` skills.

Nothing is published and no source is added: the lists stay in the uncommitted `dist/`
until the owner decides.

```sh
```

- `--match PATTERN` is a regular expression, ignoring case. It is matched against a skill
  folder's name and path, a plugin's name, or a Hermes entry's identifier, name, repository
  and hub.
- `--offset N` and `--limit N` then pick a window: skill folders for `skills-repo`, plugins
  for `claude-marketplace`, index entries for `hermes-index`. Nothing outside the window
  is fetched. The Hermes index is read as a stream and never loaded whole.
- Output goes to `dist/mirrors/<name>/index.json` and `report.md`, or to `--out DIR`.
  `dist/` is not committed.
- `report.md` lists every skill taken (upstream, file count, licence, author, notes), every
  item skipped with its reason, and a count of the reasons. "Flagged" counts skills that
  were taken but use a feature of Claude Code or Hermes that Dusk lacks. An example is
  [examples/document-design-dev-skills-report.md](examples/document-design-dev-skills-report.md),
  the `--dry-run` of `document-design-dev-skills`.

**Same input, same bytes.** Entries are sorted by name and files by path. An entry whose
pinned files did not change keeps its earlier commit and version, even when its branch has
moved on, so a re-run's diff shows only real changes. The list's `serial` goes up, and its
`expires` moves 180 days out, only when an entry changed or the list would expire within 30
days. A version is `1.<date of the pinned commit>.0`.

**Caches and limits.**
- Trees and files are cached under `.cache/mirror/`, which git ignores. They are keyed by
  commit and by git blob hash, so they never go stale. The Hermes index is kept for a day;
  `--refresh` fetches it again.
- Each branch is looked up again on every run.
- GitHub's API is used through `gh api` when `gh` is logged in (5000 requests an hour).
  Otherwise it is used over https: 60 requests an hour, or the token's quota with
  `GITHUB_TOKEN`. When the quota runs out, the run stops and says when it resets.
- A run costs about 2 requests per repository, plus 1 the first time a commit's tree is
  read. A repository too large for one tree answer costs a few more, and then only the
  skill's own folder is listed.
- Files come from `raw.githubusercontent.com`, which has no API quota but slows bursts with
  HTTP 429. The script waits and retries.
- A list holds at most 2000 entries and 4 MiB, as Dusk reads it. A larger catalogue is
  taken in slices with `--match`, `--offset` and `--limit`.

## What is taken, left out and skipped

**Files.** Kept: UTF-8 text without NUL, 1 byte to 4 MiB, on a path of `A-Z a-z 0-9 . _ -`
segments of at most 300 bytes. Scripts are kept. Left out, and counted in the entry's
notes:
- binaries, pictures and fonts
- empty files
- links and submodules
- files over 4 MiB
- paths Dusk refuses

When a skill's licence comes from its repository, the repository's licence file is pinned
into the skill's folder as `LICENSE`.

**Skipped, with the reason in the report:**
- More than 200 files.
- A name that is not `a-z 0-9 - _` (at most 64, starting with a letter or digit), or that
  the skill graph never reads (`build`, `dist`, ...).
- A `SKILL.md` that Dusk would not load, read the way `catalog/graph.rs` reads it:
  - it is over 256 KiB, or not UTF-8;
  - the front matter has no opening or closing `---`, is not valid YAML, or repeats a key;
  - `description` is missing, empty or over 1024 characters;
  - `links`, `tags`, `skills` or `tools` is not a list of words;
  - `entry` is not true or false.
- A licence that is not on the allow-list, an unrecognised licence file, or no licence
  (see below).
- A name that carries a company's word and that its front matter fixes (see "Names").
- A repository, commit or file GitHub does not serve, or a skill name already taken by an
  earlier entry of the same list.
- A name that is, or is one edit away from, one of Dusk's own (`skill-creator`,
  `skill-evolve`, `computer-use`, `token-thrift`, `duskcode`). Dusk would refuse it as
  taken.
- A list already at Dusk's cap of 2000 entries or 4 MiB. The rest of the catalogue is
  taken with `--offset`.

**Flagged, but taken.** The note goes into the entry's description, after "Notes:":
- `allowed-tools`, `disallowed-tools` or `hooks` in the front matter: Claude Code only;
  they grant and install nothing in Dusk.
- `context: fork`, `model`, `shell` or `disable-model-invocation`.
- `$ARGUMENTS`, `` !`command` `` injection, or `${CLAUDE_SKILL_DIR}`-style folders in the
  body: Dusk fills in and runs none of them.
- Hermes' `required_environment_variables`.
- Further `SKILL.md` files inside the skill. Dusk reads them as skills of their own.

The entry's description also counts the scripts the agent may ask to run, and the files
left out.

## Attribution and licences

- **Allow-list:** Apache-2.0, MIT, BSD-2-Clause, BSD-3-Clause, CC-BY-4.0 and ISC, or an
  `AND`/`OR` expression of them. Anything else is skipped and reported: GPL, MPL, CC0,
  Unlicense, proprietary, source-available, "governed by our terms", and no licence at all.
  This list is the owner's for mirrors, and it is narrower than the Workshop's own
  (`scripts/repo.py`).
- **Where the licence comes from:**
  1. the front matter `license` (or `metadata.license`), when it is an SPDX expression;
  2. otherwise, a `LICENSE*` or `COPYING*` file in the skill's folder, recognised by its
     text;
  3. otherwise, the repository's root licence file, or the licence GitHub detects for the
     repository.

  A licence file in the skill's folder wins over the repository's. An unrecognised one
  skips the skill.
- **What each entry carries:**
  - `author`: the front matter's `author` or `metadata.author`; else the mirror's `author`,
    the Hermes provider or the marketplace plugin's author; else the repository owner.
  - `license`
  - `source` and `homepage`: the GitHub tree at the pinned commit.
  - A description that ends "Not affiliated with or endorsed by <author>."
- **Files are copied byte for byte**, so licence and notice files in the skill's folder
  reach the user unchanged. Dusk does not host or modify the files: the user's Dusk fetches
  them from GitHub.
- **Leaving files out is not a modified copy.** By the owner's decision, an upstream pin
  is a pointer, not a modified copy: Dusk hosts nothing, and the binaries, fonts, images
  and empty files it leaves out stay in the author's folder at the pinned commit. Each
  entry's notes say what was left out ("2 binary files left out of the pin (they stay in
  the upstream folder)").
- **Names.** No listing, pack or mirror name or title carries a company's or an
  assistant's name; it says what the thing does. The company appears only in `author` or
  `vendor`, in `source` and the upstream repository, and in the licence text. The words
  refused are repo.py's `COMPANIES` and mirror.py's `EXTRA_COMPANIES` (`claude`, `chatgpt`,
  `gpt`, `gemini`, `copilot`, `codex`, `hermes`, `anthropics`).
  - Mirrors are named for their content: `document-design-dev-skills`,
    `skills-hub-index`, `plugin-directory-skills`, `curated-dev-skills`,
    `gpu-and-ai-infra-skills`.
  - A skill is listed under the name its front matter declares, because Dusk loads a
    skill only under that name. When the upstream folder has another name, the entry says
    so ("listed as X, the name its front matter declares; the upstream folder is Y").
  - A skill whose name carries a company word is listed without that word
    (`microsoft-foundry` becomes `foundry`) when its front matter declares no name. When
    the front matter declares the name, renaming would stop it loading, so it is skipped
    ("company in name").

## Adding a list as a source

A list is used once it is served over https. The Workshop's Pages site can carry it at
`https://drobov1tya.github.io/duskcode-workshop/mirrors/<name>/index.json`, by copying
`dist/mirrors/<name>/index.json` into `site/mirrors/<name>/` and pushing `site/`. Any https
host works if it serves the file without redirects, at a public address, with no query
string or credentials in the address.

A user adds it in one of three ways. Each way makes it an Unverified source, and a
source's name is `a-z 0-9 -`, at most 32 characters:

- **Settings → Workshop sources:** give a name and the list's address, and leave the key
  empty.
- **`config.yml`:** add the source without a `key`:

  ```yaml
  workshop:
    sources:
      - name: document-design-dev-skills
        url: https://drobov1tya.github.io/duskcode-workshop/mirrors/document-design-dev-skills/index.json
  ```

- **From a chat:** the agent calls `add_workshop_source { name, url }`, with no `key`.
  This only proposes the source. The user is asked every time, in every mode, full access
  included, and is shown that the source is Unverified and what it may bring. Only the
  desktop app or the terminal can answer, not a browser or a chat platform.

An agent asked to "connect the Hermes skills for X":

1. Runs `scripts/mirror.py skills-hub-index --survey`, then
   `scripts/mirror.py skills-hub-index --match '<what the user asked for>' --limit N --out <folder>`.
   `--limit` keeps the GitHub requests bounded.
2. Goes through `report.md` with the user: what was taken, what was skipped, and the notes.
3. Publishes `index.json` at an https address the user controls.
4. Proposes that address with `add_workshop_source`.

Nothing from Hermes or the Claude marketplace is published by default. Those mirrors are
`manual` in `mirrors.yml`.

## Checking a list

`scripts/check-index.py --unsigned <index.json>` checks a list against Dusk's rules for
keyless sources:
- format 3, not expired, at most 2000 entries and 4 MiB;
- only skills, packs and agents pinned upstream, with no packages, pictures or stars;
- the `upstream` rules of `upstream.rs`: `owner/name`, a 40-hex commit, 1 to 200 files,
  plain paths, sizes and hashes;
- a skill's or agent's files all under `<name>/`, with its `SKILL.md` or `AGENT.md`.

`--fetch [NAME ...]` also downloads the pinned files and checks each one's size, SHA-256
and UTF-8 text, and that each `SKILL.md` loads.

## Pinned packs of the official list

The same converter fills the **signed official list** with reviewed third-party packs
that are pinned in their authors' repositories, not copied here:

- `pinned/<pack>/pack.yml` is written by hand and reviewed. It holds:
  - the name, title and description (neutral, saying what the pack does);
  - `vendor` and `license`;
  - the GitHub `repo` and the reviewed `commit`;
  - `items`: each skill mapped to its folder in that repository.
- `pinned/<pack>/pins.json` is written by `scripts/mirror.py --pin <pack>`. Each item goes
  through the converter's rules: text only, the caps, the front matter, the licence within
  the pack's, names that load. The file holds the commit, the SHA-256 and size of every
  file, and each item's notes.
- One upstream pins at most 200 files, so a larger source is split into packs by subject.
- `scripts/check-index.py --repo .` checks both files.
- `scripts/publish.py --format=3` turns each pack into a list entry with `upstream`
  instead of a package. Dusk fetches exactly those files from GitHub and checks each hash.
  A format 2 list leaves these packs out, and says so.
- In the app, the listing is Verified (somebody else's work in the official list). It
  shows `github.com/<repo> at <commit>` and the author; the install record keeps the tree
  address.
- To refresh a pack: `scripts/mirror.py --pin <pack> --bump` moves it to the current
  commit. Review the diff of `pins.json` and the upstream changes, then sign.
- CI (`.github/workflows/check.yml`) runs `scripts/check-index.py --pins` on every change
  and weekly. It fails when an author's repository no longer serves a pinned file with its
  hash.
