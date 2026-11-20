# Work from other authors

What each pack that came from an upstream owes its license, checked against the upstream
repositories on 2026-11-18. This is a working note, not legal advice.

| Pack | Author | Source | License | Copying with credit | Kept here |
| --- | --- | --- | --- | --- | --- |
| web-builder-skills | Anthropic | https://github.com/anthropics/skills (`skills/<item>/LICENSE.txt`; the repository has no root license) | Apache-2.0 | allowed (section 4) | `LICENSE.md` and `NOTICE.md` per item; changes named in `SKILL.md` and `NOTICE.md` |
| dev-workflow-skills | OpenAI; `playwright` derives from Microsoft's playwright-cli | https://github.com/openai/skills (`skills/.curated/<item>/LICENSE.txt`; no root license) | Apache-2.0 | allowed (section 4) | `LICENSE.md` and `NOTICE.md` per item; the upstream `NOTICE.txt` of `playwright` kept as its `NOTICE.md` |
| gpu-computing-skills | NVIDIA | https://github.com/NVIDIA/skills (`LICENSE-CC-BY-4.0`, `LICENSE-APACHE`) | CC-BY-4.0 (text) AND Apache-2.0 (code) | allowed (CC BY 4.0 section 3(a); Apache section 4) | both license texts and `NOTICE.md` per item, with the upstream commit |

## What the licenses ask, and where it is met

- **Apache-2.0, section 4.** Give a copy of the license (`LICENSE.md` / `LICENSE-APACHE.txt`
  in each item); say that changed files were changed (`changes` in the front matter and
  `NOTICE.md`); keep the copyright and attribution notices of the source; carry the
  upstream `NOTICE` when there is one (only `playwright` has one). Section 6 gives no right
  to the licensor's names or marks beyond describing where the work came from.
- **CC-BY-4.0, section 3(a).** Name the creator, keep the copyright notice, the license
  notice and the disclaimer, link to the material, and say what was changed (`NOTICE.md`
  in each item). Section 2(a)(6): nothing may suggest the licensor endorses the use.
- A pack's upstream commit is recorded only for gpu-computing-skills. When the other two
  are next refreshed from upstream, write the commit into each `NOTICE.md`.

## Names

No id, title or cover carries a company's or a product's name. The two packs from
Anthropic and OpenAI were titled "Skills for Claude" and "Skills for GPT" until
2026-11-19; their titles are now "Web Builder Skills" and "Developer Workflow Skills",
which say what the packs hold. Their ids did not change. Anthropic's trademark guidelines
allow its marks only as it specifically permits, and OpenAI's brand page could not be read
(it answered 403); a title is not the place to rely on either.

The author is named as a fact in `vendor`, `upstream`, the notices and one clause of the
description, each description ends with "Not affiliated with or endorsed by <author>", and
no logo is used.

## Packs pinned in their authors' repositories

Checked on 2026-11-19. These packs copy nothing: `pinned/<pack>/pins.json` names the
author's files at one commit with their SHA-256, and duskcode fetches them from GitHub.
The licence and notice files of each skill's folder are pinned with it byte for byte.
Where a licence sits only at the repository's top (NVIDIA's `LICENSE-APACHE` and
`LICENSE-CC-BY-4.0`), those files are pinned into each skill's folder. Leaving out the
upstream's binaries (fonts, images) makes the pin a pointer, not a modified copy, by the
owner's decision; each skill's notes in `pins.json` say what was left out.

| Packs | Author | Source, commit | License |
| --- | --- | --- | --- |
| office-document-skills, visual-design-skills, communication-skills | Anthropic | https://github.com/anthropics/skills `e4bb5d9` (`skills/<item>/LICENSE.txt`) | Apache-2.0 |
| hosting-deploy-skills, team-workspace-skills, dotnet-app-skills, speech-audio-skills, repository-utility-skills | OpenAI | https://github.com/openai/skills `49f948f` (`skills/.curated/<item>/LICENSE.txt`) | Apache-2.0; `vercel-deploy` and the four Notion skills MIT |
| tile-kernel-skills, gpu-simulation-skills, multi-gpu-memory-skills, optimization-solver-skills, gpu-acceleration-skills | NVIDIA | https://github.com/NVIDIA/skills `b0694f6` (front matter `license`, root `LICENSE-*`) | Apache-2.0, or CC-BY-4.0 (text) AND Apache-2.0 (code) |

**What was left out, and why.**
- anthropics/skills:
  - `frontend-design`, `mcp-builder` and `webapp-testing` are already in
    web-builder-skills.
  - `skill-creator` is the name of a duskcode built-in skill.
  - `claude-api`'s description is over 1024 characters, so it would not load.
  - `doc-coauthoring` has no licence file.
  - `academy-guide` points users to the vendor's own courses, and `brand-guidelines`
    applies the vendor's brand; neither is useful as a neutral pack.
- openai/skills:
  - The six skills of dev-workflow-skills are already there.
  - `chatgpt-apps`, `openai-docs` and `migrate-to-codex` declare names with an
    assistant's or company's word.
  - The eight Figma skills are under Figma's own terms ("governed by the Figma Developer
    Terms"), not an allowed licence.
  - `cloudflare-deploy` has 311 files.
  - `skill-creator` is a built-in name.
  - `cli-creator`, `hatch-pet`, `imagegen`, `define-goal`, `playwright-interactive`,
    `plugin-creator` and `skill-installer` are written for another agent's own tools.
- NVIDIA/skills: only five subjects of its 472 skills are packed. `compute-sanitizer` and
  `cudf` are already in gpu-computing-skills. The rest (robotics, medical imaging, data
  centre networking and others) can be packed the same way when wanted.

**Review.** Every pinned text file was scanned for:
- instructions to hide things from the user or to ignore earlier instructions;
- piping a download into a shell;
- base64 decoding;
- reading `~/.ssh` or cloud credentials;
- exfiltration;
- bidi and zero-width characters.

The six hits are benign:
- apt and `/tmp` clean-ups;
- an evaluation case that checks the skill *refuses* `curl | bash`;
- a security note in a benchmark;
- `render-deploy` and `sentry`, which show their vendors' official CLI installers
  (`curl … | sh`) as an instruction. The agent runs that only through the user's command
  approval.

Scripts are kept, and each skill's notes count them. `warp-compile-time-optimizer` names
`allowed-tools`, which grants nothing in duskcode.

Names and titles say what the packs do; the authors appear only in `vendor`, `repo`, the
licence files and the "Not affiliated with or endorsed by" clause, and the covers are the
Workshop's own generated ones.
