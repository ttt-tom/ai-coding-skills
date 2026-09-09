---
name: efficient-code-maintenance
description: Set up AGENTS.md and repository maintenance workflows, find who calls a function, or prepare an evidence-based handoff. Use for repository bug fixes that need navigation and isolated reproduction, or when asked to reduce repeated AI code exploration; lightweight edits need not adopt the full workflow.
---

# Efficient Code Maintenance

Use the project's existing conventions and the user's requested scope. A review does not authorize a fix, a fix does not authorize deployment, and persistence does not expand permissions.

## Establish a project

When asked to set up the workflow, adapt the self-contained templates in `templates/` relative to this skill directory.
Merge existing instructions instead of replacing them. Keep one requirement source of truth; link existing issue tracking instead of duplicating it. Define observable acceptance and non-goals, not a speculative architecture.
When asked to configure ignores, review and merge `templates/gitignore-ai.txt`. Keep shared rules/skills tracked; exclude only applicable local runtime data. These are conservative examples, not an installer or a guarantee of all client storage paths. Review tracked files separately for secrets.

## Maintain a project

Use this sequence for non-trivial maintenance:
1. Inspect `git status --short` and the current handoff. Output: task boundary and writer ownership.
2. Locate the entry and callers with rg/LSP or the commands below. Output: one evidence-backed hypothesis with source locations.
3. Reproduce offline, then patch. Output: failing-before/passing-after test evidence and a reviewable diff.
4. Verify and hand off. Output: outcome, changed files, actual checks, unverified items and next step. See the filled example in `templates/ACTIVE_HANDOFF.md`.

- Start with working-tree changes, project instructions, current handoff and code map if present. Inspect only what is needed; a trivial edit need not create planning documents.
- State the specific question. Use symbol search/LSP or the bundled Python index to find entry, relevant caller, and output consumer. Read complete relevant functions; do not enforce an arbitrary file-count limit.
- If two inspection passes add no evidence, write a reproducer or identify the concrete blocker rather than repeat overlapping reads. Source changed or a new hypothesis is a reason to re-read.
- For a defect, prefer a failing isolated test then the smallest coherent patch. For new functionality, use explicit acceptance criteria. Do not combine unrelated refactors with a fix.
- Confirm test isolation before execution: fake network/provider/subprocess boundaries and temporary storage. A mock of the wrong function does not isolate a subprocess. Never run a live acceptance script merely because its name contains test.
- Validate proportional to risk. Distinguish syntax checks, unit tests, integration tests and live acceptance; report only those actually run.
- Update a short handoff when work will continue: facts vs hypotheses, owned files, commands/results, unverified items and next question. Do not reproduce raw logs or source bodies.

## Navigation helper

From this skill directory, run:

```sh
python scripts/code_index.py query snapshot --root REPO --rebuild
python scripts/code_index.py query snapshot --callers --root REPO --rebuild
python scripts/code_index.py query snapshot --callers --file src/store.py --root REPO --rebuild --json
```

`--rebuild` refreshes missing/stale data before answering. Add repeatable `--exclude DIRECTORY` on every command for project-specific exclusions. Exact matches take priority over substring matches.
`--json` returns results, total count and truncation metadata without progress text on stdout. `--file` filters returned definition/caller locations; it does not resolve callee identity.
The helper reads only tracked Python source and writes local `.code-index/symbols.json`.
It never imports project modules. Add the output directory to project ignores with authorization.
Do not add unknown files to Git solely to index them. Inspect untracked files directly.
For other languages use existing LSP/rg; do not claim Python indexing covers them.
Calls are ambiguous syntactic candidates, not resolved runtime edges. The helper does not infer test coverage.

## Collaboration and delivery

One writer per overlapping file unless explicitly coordinated. Delegation and publishing require the user's authorization; this skill does not grant it.
Keep patches independently reviewable, preserve other work, and state rollback limitations.
Do not automatically commit, push, reset credentials, deploy, or run paid requests.
Optimize for correct progress with bounded context, not fewer reads at the expense of correctness. Measure improvements before claiming token savings.
