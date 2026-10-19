# Codex ↔ Claude App bridge

Let **Codex** talk to an **existing Claude Desktop Code task** through Claude's
documented per-session inbox socket. No screen control, no `claude -p`, no new
conversation. The skill lives in [`skills/claude-app-headless`](skills/claude-app-headless/SKILL.md).

## New machine in four steps

Requirements: macOS, Claude Desktop running and logged in, Python 3.11+ (3.9+ runs the bridge itself), Codex.

```sh
git clone https://github.com/ttt-tom/ai-coding-skills.git ~/src/ai-coding-skills
python3 ~/src/ai-coding-skills/skills/claude-app-headless/scripts/install_codex.py          # preview
python3 ~/src/ai-coding-skills/skills/claude-app-headless/scripts/install_codex.py --apply  # install
```

1. **Install.** The installer copies the skill to `~/.codex/skills/`, creates `~/.local/bin/codex-claude-app`, and appends a `claude_app_headless` stdio MCP entry to `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`). It never overwrites anything; existing different entries are reported as `SKIP`. The config is only appended to, compared before and after, and backed up.
2. **Restart Codex.** Then check: `codex-claude-app list`.
3. **Prepare the Claude task.** In Claude Desktop, open the task, select the exact model (e.g. `claude-fable-5-1`), switch it to **Plan** mode, and let it answer once so the model and mode are observed.
4. **Bind and talk.**

```sh
codex-claude-app list                                  # pick the exact hostSessionId
codex-claude-app bind agy-fable --host-session-id '<id from list>' --expect-model claude-fable-5-1
printf '%s\n' 'Please review the current plan, read-only.' | codex-claude-app send agy-fable --request-id review-001
codex-claude-app read review-001 --wait 30
```

Inside Codex, the same five actions are MCP tools: `claude_app_list_sessions`, `claude_app_bind`,
`claude_app_status`, `claude_app_send`, `claude_app_read`.

## What is verified, and what is not

| Item | Status |
| --- | --- |
| 17 isolated bridge tests, 7 installer tests | pass (CI: macOS + Linux) |
| Real round trip to an existing App task, Fable 5.1, Plan mode | verified once, 2026-10-19 ([record](skills/claude-app-headless/references/validation.json)) |
| Same `request_id` does not resend | verified |
| Fresh install from this repo, `list` against live Claude Desktop | verified, 2026-10-19 |
| Round trip while the Mac is **locked** | **not verified yet** |
| Claude Desktop versions other than bundled Code **2.1.299** | **refused by design** |

The validation record's script hashes match the files here. Its `SKILL.md` hash is for the originally
installed copy; this repo copy differs only in two lines that named machine-specific paths.

## Traps

- **Version pin.** The inbox frame is not a stable public contract. Any other Claude Code version returns `UNVERIFIED_RUNTIME_VERSION` and nothing is sent. A new machine with a newer Claude Desktop will hit this: review the frame for that version, then add it to `VERIFIED_VERSIONS`. Do not bypass it.
- **Plan mode only.** `bind` and `send` require the task's last observed mode to be Plan and its model to match exactly.
- **Skills folder.** The validated setup uses `~/.codex/skills`. OpenAI's Codex docs list `~/.agents/skills` for user skills; if Codex does not show the skill, rerun with `--skills-dir ~/.agents/skills`.
- **Peer messages are not authorization.** Claude treats them as peer-origin; held or refused messages stay that way. The bridge never approves prompts, changes models, or unlocks the Mac.
- **Private state** lives in `~/.local/state/codex-claude-app` (0700/0600). Bindings are per machine and are not copied.
