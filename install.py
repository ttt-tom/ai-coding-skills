#!/usr/bin/env python3
"""Preview-first installer for the efficient-code-maintenance skill.

Default action is a preview: nothing is written. Pass --apply to write.
Existing files and directories are never overwritten or edited; for an
existing instruction file the installer prints a snippet to merge by hand.
Standard library only; Python 3.9+.
"""
import argparse
import filecmp
import json
import os
from pathlib import Path
import shutil
import sys

SKILL_NAME = 'efficient-code-maintenance'
HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'skills' / SKILL_NAME
MARKER = 'ai-coding-skills'

# Paths below were read from each vendor's documentation on 2026-09-09.
# See INSTALL.md for the source URL of every row. "Docs-verified" means the
# path is documented; it does not mean this installer was exercised end to end
# inside that product.
CLIENTS = {
    'claude-code': dict(
        project='.claude/skills', user='~/.claude/skills', instructions='CLAUDE.md',
        note='Claude Code reads CLAUDE.md, not AGENTS.md; a created CLAUDE.md imports AGENTS.md with @AGENTS.md.'),
    'codex': dict(
        project='.agents/skills', user='~/.agents/skills', instructions='AGENTS.md',
        note='Codex also reads AGENTS.override.md first when present.'),
    'gemini-cli': dict(
        project='.agents/skills', user='~/.agents/skills', instructions='GEMINI.md',
        note='Default context file is GEMINI.md; AGENTS.md is read only if context.fileName lists it.'),
    'antigravity': dict(
        project='.agents/skills', user='~/.gemini/config/skills', instructions=None,
        note='Workspace rules live in .agents/rules/*.md (12k chars each); not written by this installer.'),
    'cursor': dict(
        project='.agents/skills', user='~/.agents/skills', instructions='AGENTS.md',
        note='Cursor also loads .cursor/skills and, for compatibility, .claude/skills and .codex/skills.'),
    'copilot': dict(
        project='.agents/skills', user='~/.agents/skills', instructions='AGENTS.md',
        note='Copilot also reads .github/skills and .github/copilot-instructions.md.'),
    'windsurf': dict(
        project='.windsurf/skills', user='~/.codeium/windsurf/skills', instructions='AGENTS.md',
        note='Product is now documented as Devin Desktop; .devin/skills is the newer alias.'),
    'zed': dict(
        project='.agents/skills', user='~/.agents/skills', instructions='AGENTS.md',
        note='Zed loads only the FIRST of .rules, .cursorrules, .windsurfrules, .clinerules, '
             '.github/copilot-instructions.md, AGENT.md, AGENTS.md, CLAUDE.md, GEMINI.md.'),
}

POINTER = f"""<!-- {MARKER}:begin -->
## Maintenance workflow

This project uses the `{SKILL_NAME}` skill (see `{{skill_path}}/SKILL.md`).
For non-trivial maintenance: locate the entry and callers, reproduce offline,
make the smallest coherent patch, verify, and leave a short handoff.
Merge with existing rules; a review does not authorize a fix, and a fix does
not authorize deployment.
<!-- {MARKER}:end -->
"""


def pointer_text(skill_path, header):
    body = POINTER.format(skill_path=skill_path)
    return f'# {header}\n\n{body}' if header else body


def identical(source, target):
    """True when every file under source exists in target with equal bytes."""
    if not target.is_dir():
        return False
    for file in source.rglob('*'):
        if file.is_file():
            other = target / file.relative_to(source)
            if not other.is_file() or not filecmp.cmp(str(file), str(other), shallow=False):
                return False
    return True


def plan(root, clients, scope, home, link=False):
    """Return a list of action dicts. Pure: touches nothing."""
    actions = []
    seen = set()
    skill_dirs = []
    for client in clients:
        spec = CLIENTS[client]
        base = spec[scope]
        target = (home / base[2:]) if base.startswith('~/') else (root / base)
        target = target / SKILL_NAME
        if target in seen:
            continue
        seen.add(target)
        skill_dirs.append(target)
        if target.exists() or target.is_symlink():
            status = 'up-to-date' if identical(SOURCE, target) else 'skip-exists'
            actions.append(dict(kind='skill', status=status, path=str(target), client=client))
        else:
            actions.append(dict(kind='skill', status='link' if link else 'create',
                                path=str(target), client=client))
    if scope != 'project':
        return actions
    wanted = {CLIENTS[c]['instructions'] for c in clients if CLIENTS[c]['instructions']}
    first_skill = skill_dirs[0].relative_to(root).as_posix() if skill_dirs else SKILL_NAME
    if 'CLAUDE.md' in wanted and len(wanted) > 1:
        wanted.discard('CLAUDE.md')
        wanted.add('CLAUDE.md:import')
    for name in sorted(wanted):
        file, _, mode = name.partition(':')
        path = root / file
        if path.exists():
            actions.append(dict(kind='instructions', status='suggest', path=str(path),
                                snippet=pointer_text(first_skill, None)))
        elif mode == 'import':
            actions.append(dict(kind='instructions', status='create', path=str(path),
                                content='@AGENTS.md\n'))
        else:
            actions.append(dict(kind='instructions', status='create', path=str(path),
                                content=pointer_text(first_skill, 'Project working agreement')))
    return actions


def apply(actions):
    for action in actions:
        path = Path(action['path'])
        if action['status'] == 'create' and action['kind'] == 'skill':
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SOURCE, path)
        elif action['status'] == 'link':
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(SOURCE, path, target_is_directory=True)
        elif action['status'] == 'create':
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'x', encoding='utf-8') as handle:  # 'x': never overwrite
                handle.write(action['content'])
        action['done'] = action['status'] in ('create', 'link')
    return actions


def render(actions, applied, notes):
    verb = 'Applied' if applied else 'Preview (nothing written; add --apply)'
    lines = [f'{verb}:']
    for a in actions:
        label = {'create': 'CREATE', 'link': 'SYMLINK', 'skip-exists': 'SKIP  ',
                 'up-to-date': 'OK    ', 'suggest': 'MERGE '}[a['status']]
        lines.append(f"  {label} {a['kind']:<12} {a['path']}")
    suggestions = [a for a in actions if a['status'] == 'suggest']
    if suggestions:
        lines.append('\nExisting instruction files were left untouched. Merge this block by hand:\n')
        lines.append(suggestions[0]['snippet'])
    if any(a['status'] == 'skip-exists' for a in actions):
        lines.append('SKIP: a different copy already exists; compare and update it yourself.')
    if notes:
        lines.append('\nClient notes:')
        lines.extend(f'  - {c}: {n}' for c, n in notes)
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--client', action='append', choices=sorted(CLIENTS) + ['all'],
                        help='repeatable; default: all')
    parser.add_argument('--scope', choices=['project', 'user'], default='project')
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='project root (default: cwd)')
    parser.add_argument('--apply', action='store_true', help='write files; default is preview only')
    parser.add_argument('--link', action='store_true', help='symlink the skill instead of copying (POSIX)')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--home', type=Path, default=Path.home(), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    clients = sorted(CLIENTS) if not args.client or 'all' in args.client else sorted(set(args.client))
    if not (SOURCE / 'SKILL.md').is_file():
        parser.exit(2, f'Skill source missing: {SOURCE}\n')
    root = args.root.resolve()
    if args.scope == 'project' and not root.is_dir():
        parser.exit(2, f'Not a directory: {root}\n')
    actions = plan(root, clients, args.scope, args.home.expanduser().resolve(), args.link)
    if args.apply:
        apply(actions)
    if args.json:
        print(json.dumps(dict(applied=args.apply, scope=args.scope, actions=actions), indent=2))
    else:
        print(render(actions, args.apply, [(c, CLIENTS[c]['note']) for c in clients]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
