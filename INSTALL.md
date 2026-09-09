# Install for your AI client

`install.py` copies the `efficient-code-maintenance` skill into the directories
each client documents, and creates a pointer in the project instruction file
**only if that file does not exist**. It never overwrites, edits or deletes
anything. The default run is a preview; nothing is written until `--apply`.

```sh
git clone https://github.com/ttt-tom/ai-coding-skills.git
cd /path/to/your/project
python /path/to/ai-coding-skills/install.py                 # preview, all clients
python /path/to/ai-coding-skills/install.py --client cursor --client claude-code --apply
python /path/to/ai-coding-skills/install.py --scope user --client zed --apply   # personal, all projects
```

Options: `--client NAME` (repeatable; `all` by default), `--scope project|user`,
`--root DIR`, `--apply`, `--link` (symlink instead of copy, POSIX only), `--json`.
Requires Python 3.9+, standard library only.

## For an AI assistant given this repository link

Do this, in order, and stop before `--apply` unless the user has approved the preview:

1. Clone the repository and read `skills/efficient-code-maintenance/SKILL.md`.
2. Run `python install.py --client <the user's client>` from the user's project root and show the preview.
3. If the preview reports `MERGE`, an instruction file already exists: paste the printed block into it by hand and do not replace the file.
4. Only after approval, rerun with `--apply`. Then confirm the skill appears in the client (see the per-client check below).

## Verification status

"Docs-verified" means we read the vendor's official documentation on the date shown
and the installer writes to exactly those paths. It does **not** mean we ran each
product end to end. Rows marked "runtime-tested" were exercised inside the product.
Nothing is currently runtime-tested; contributions with a screenshot or session log are welcome.

Checked 2026-09-09. Vendors move paths; if a row is stale, open an issue with the new URL.

| Client | Project skill dir written | User skill dir written | Instruction file | Status | Source |
| --- | --- | --- | --- | --- | --- |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` | `CLAUDE.md` (created as `@AGENTS.md` import when AGENTS.md is also created) | docs-verified | [skills](https://code.claude.com/docs/en/skills), [memory](https://code.claude.com/docs/en/memory) |
| Codex (OpenAI) | `.agents/skills/` | `~/.agents/skills/` | `AGENTS.md` | docs-verified | [skills](https://developers.openai.com/codex/skills/), [AGENTS.md](https://developers.openai.com/codex/guides/agents-md) |
| Gemini CLI | `.agents/skills/` (alias of `.gemini/skills/`) | `~/.agents/skills/` | `GEMINI.md` | docs-verified | [skills](https://geminicli.com/docs/cli/skills/), [gemini-md](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/gemini-md.md) |
| Antigravity (Google) | `.agents/skills/` | `~/.gemini/config/skills/` | none written; rules live in `.agents/rules/*.md` | docs-verified | [skills](https://antigravity.google/docs/skills), [rules](https://antigravity.google/docs/rules-workflows) |
| Cursor | `.agents/skills/` | `~/.agents/skills/` | `AGENTS.md` | docs-verified | [skills](https://cursor.com/docs/context/skills), [rules](https://cursor.com/docs/context/rules) |
| GitHub Copilot | `.agents/skills/` | `~/.agents/skills/` | `AGENTS.md` | docs-verified | [agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills), [instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions) |
| Windsurf (now Devin Desktop) | `.windsurf/skills/` | `~/.codeium/windsurf/skills/` | `AGENTS.md` | docs-verified | [skills](https://docs.windsurf.com/windsurf/cascade/skills), [rules](https://docs.windsurf.com/windsurf/cascade/memories) |
| Zed | `.agents/skills/` | `~/.agents/skills/` | `AGENTS.md` | docs-verified | [skills](https://zed.dev/docs/ai/skills), [instructions](https://zed.dev/docs/ai/instructions) |

Six of eight clients read `.agents/skills/`, so a project install for `all` writes the skill three times
(`.agents/`, `.claude/`, `.windsurf/`). Use `--link` on macOS/Linux to keep one copy.

## Per-client check after install

- **Claude Code**: run `/context`; the skill should be listed and `CLAUDE.md` under Memory files.
- **Codex**: type `$efficient-code-maintenance` in the CLI or IDE.
- **Gemini CLI**: `/skills list`. Gemini also documents `gemini skills install <repo-url>`; not tested here.
- **Antigravity, Cursor, Zed, Windsurf, Copilot**: the skill appears in the skills list or via `/` (Cursor, Zed), `@skill-name` (Windsurf, Zed).

## Traps we know about

- **Zed reads one instruction file only**, the first found in this order: `.rules`, `.cursorrules`, `.windsurfrules`, `.clinerules`, `.github/copilot-instructions.md`, `AGENT.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`. If your project has `.cursorrules`, Zed ignores `AGENTS.md`.
- **Claude Code does not read AGENTS.md.** The created `CLAUDE.md` imports it with `@AGENTS.md`. On Windows this import is the documented alternative to a symlink.
- **Gemini CLI reads GEMINI.md by default.** To share `AGENTS.md`, set `context.fileName` in its settings.json.
- **Codex** honours `AGENTS.override.md` before `AGENTS.md`; a 32 KiB default cap applies.
- **Zed and Antigravity require skills to be direct children** of the skills root; nested folders are not discovered.
- The pointer block is wrapped in `<!-- ai-coding-skills:begin/end -->` comments so a later merge or removal is easy to spot.
