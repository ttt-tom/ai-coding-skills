<div align="center">

# ✦ AI Coding Skills

### Less wandering. Clearer patches. Better handoffs.

A small, portable workflow for AI-assisted coding.<br>
**By [ttt-tom](https://github.com/ttt-tom)** · Local-first · MIT licensed

[![Offline checks](https://github.com/ttt-tom/ai-coding-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/ttt-tom/ai-coding-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/optional%20index-Python%203.9%2B-3776AB.svg)](#optional-python-index)

[Get started](#start-in-one-minute) · [中文说明](#中文一分钟了解) · [The skill](skills/efficient-code-maintenance/SKILL.md) · [Roadmap](PROJECT.md)

</div>

---

Your AI keeps rereading the same files. The next session forgets what changed. A “fix” arrives without a test.

**Give it a repeatable way to work:**

**Locate → Reproduce → Patch → Verify → Hand off**

No vector database. No service to run. No API key for the tooling.<br>
Keep your existing editor, agent and search tools.

## Start in one minute

**1. Get the skill.**

```sh
git clone https://github.com/ttt-tom/ai-coding-skills.git
```

**2. Give your AI this prompt.**

> Read `ai-coding-skills/skills/efficient-code-maintenance/SKILL.md`. Apply it to my project: identify the relevant entry and callers, reproduce the issue offline, make the smallest coherent fix, and leave verified results plus the next step. Merge existing project rules; do not overwrite them.

Adjust the path to where you cloned the repository. If your client supports skill folders, you can instead copy **the entire** `skills/efficient-code-maintenance/` directory into its documented skills location. Templates, script and license travel with it.

**3. Start small.** One bug, one acceptance criterion, one handoff.<br>
You do **not** need the Python index to use the workflow.

### Install into your client (preview first)

```sh
cd /path/to/your/project
python /path/to/ai-coding-skills/install.py                       # preview only
python /path/to/ai-coding-skills/install.py --client cursor --apply
```

The installer copies the skill to the directories each client documents and never
overwrites or edits existing rules; when an `AGENTS.md`/`CLAUDE.md` already exists it
prints a block for you to merge. Claude Code, Codex, Gemini CLI, Antigravity, Cursor,
Copilot, Windsurf and Zed paths are **docs-verified, not runtime-tested**. Details,
sources and known traps: [INSTALL.md](INSTALL.md).

**Handing this to an AI?** Give it the link and say: *"Read INSTALL.md in
https://github.com/ttt-tom/ai-coding-skills and run the installer preview for my client; do not apply until I approve."*

Keep **team instructions** in Git and **private runtime data** out. The included [.gitignore](.gitignore) covers local settings, credentials and session/cache folders without excluding entire tool directories. Some local filenames are project conventions, not client defaults.

For a new project, merge the optional [AI/editor ignore snippet](skills/efficient-code-maintenance/templates/gitignore-ai.txt); review existing rules rather than replacing them. An ignore rule does not remove already-tracked secrets, and a shared settings file is not automatically safe to publish.

## What you get

| Piece | What it helps with |
| --- | --- |
| **One skill** | A shared working method across sessions and assistants |
| **Four templates** | Project acceptance, working rules, code map and active handoff |
| **Optional Python index** | Find definitions and candidate callers without importing your app |
| **Preview-first installer** | Copies the skill into 8 clients' documented paths without touching existing rules |
| **Offline tests** | Check packaging, freshness, query output, path handling and the installer |

Templates live [inside the skill](skills/efficient-code-maintenance/templates). Existing issue trackers remain the source of truth—no duplicate project-management system.

## A concrete example

**Before:** “Fix this bug.” → repeated file scans → speculative patch → next session starts over.

**With the workflow:**

1. Ask “Who calls `snapshot`?”
2. Read the relevant function and caller.
3. Write a failing test; make it pass.
4. Hand off: “Changed X. Test Y passed. Live behavior is not yet verified.”

This illustrates the process, **not a measured speed or token-saving claim**.

## Optional Python index

Requires **Python 3.9+ and Git**. From this repository:

```sh
# Who calls snapshot? Refresh stale data before answering.
python skills/efficient-code-maintenance/scripts/code_index.py query snapshot --callers --rebuild --root /path/to/project

# Machine-readable results; narrow returned callers to one file.
python skills/efficient-code-maintenance/scripts/code_index.py query snapshot --callers --file src/store.py --json --rebuild --root /path/to/project
```

Replace `/path/to/project` with your Git repository path; quote paths with spaces. On systems that use `python3`, substitute that command.

<details>
<summary><strong>Options, limits & privacy</strong></summary>

- `build` writes a local index; `check` verifies freshness.
- `query SYMBOL` prefers exact names, then substring matches.
- `--callers` returns syntactic candidate callers, not a resolved call graph.
- `--file PATH` filters **returned locations** by exact repository-relative path; it does not resolve which same-named method is called.
- `--json` emits one object with `results`, `total`, `truncated` and `warning`. At most 20 matches are returned. Errors go to stderr with a nonzero exit.
- `--rebuild` refreshes missing/stale indexes before queries. Without it, stale queries fail rather than return old locations.
- Repeat `--exclude DIRECTORY` for project-specific directory names, using the same options on each command. Defaults skip hidden directories, vendor, node_modules and __pycache__.
- Only **Git-tracked Python files** are indexed. Inspect untracked files directly; never stage unknown files just to index them.
- No application imports, source bodies, default values or docstrings are stored. Names and paths can still reveal business structure: keep `.code-index/` local and add it to project ignores.
- For other languages, use your existing **rg/LSP**. The workflow and templates are cross-language; this parser is not.
- No auto-deployment, credential changes or paid requests. Tests passing is not production acceptance.

</details>

## Try it, measure it, keep what helps

The baseline is **the same workflow with rg + LSP**, not “no tools.” We will compare locating time, refresh overhead, repeated reads, actual tokens when available and patch correctness across two real projects.

If the index adds no consistent value, remove it. **The workflow and templates stand on their own.** See the [evaluation plan](PROJECT.md); benchmarks are not yet available.

## Contribute

Small, reproducible improvements are welcome. Open an issue with the task, expected behavior, actual behavior and a sanitized example—never upload keys or private source.

```sh
python -m unittest discover -s tests
```

CI runs on Ubuntu and Windows with Python 3.9 and 3.12. macOS is covered by local testing.

## 中文：一分钟了解

**让 AI 少盲搜、多验证，下一次会话也能接着做。** 项目由 **[ttt-tom](https://github.com/ttt-tom)** 创建和维护。

- 核心：一份技能＋四份模板，让需求、代码入口、验证证据和交接有据可查。
- 使用：克隆仓库，让 AI 阅读技能的 `SKILL.md`；或运行 `python install.py` 预览后 `--apply`，安装到 Claude Code / Codex / Gemini CLI / Antigravity / Cursor / Copilot / Windsurf / Zed 的官方目录，不覆盖已有规则。路径经官方文档核对，未逐一实机验证，见 [INSTALL.md](INSTALL.md)。
- 流程：**定位 → 离线复现 → 最小修改 → 验证 → 交接**。
- Python 索引是可选助手；其他语言继续用 rg/LSP。不承诺未经实测的 token 节省。
- README 和技能优先使用英文面向全球开发者；本节与立项书保留中文说明。
- MIT 开源，可复用和修改，请保留许可证中的版权声明。

---

Created and maintained by **[ttt-tom](https://github.com/ttt-tom)**.<br>
[MIT License](LICENSE) · The standalone skill includes its own license copy.
