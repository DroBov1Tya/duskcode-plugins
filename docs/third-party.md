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

No id, title or cover carries a company's name, and no id or cover a product's. Two
titles name the product the skills were written for, by the owner's decision:
web-builder-skills is "Skills for Claude" and dev-workflow-skills is "Skills for GPT".
What the brand pages say about that (read 2026-11-18):

- Anthropic's trademark guidelines allow its marks only as it specifically permits, in
  material it approved, and forbid implying sponsorship or endorsement. They say nothing
  of "for Claude" titles, so the title rests on descriptive use, not on a permission.
- OpenAI's brand page could not be read (it answered 403). Summaries of it say "GPT" is
  not permitted in product names, and that "powered by GPT-4" or "<name> plugin for
  ChatGPT" is the accepted form. By that reading "Skills for GPT" is outside the
  guidelines; read the live page before publishing.
- The safest wording keeps both marks out of titles ("Web Builder Skills", "Developer
  Workflow Skills"); changing back is one line of each `pack.yml`, and the ids stay.

The author is named as a fact in
`vendor`, `upstream`, the notices and one clause of the description, each description
ends with "Not affiliated with or endorsed by <author>", and no logo is used.
