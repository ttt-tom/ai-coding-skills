#!/usr/bin/env python3
"""Preview-first installer: Codex -> existing Claude Desktop Code task bridge.

Installs three things on this machine, and only with --apply:
  1. this skill folder into a Codex skills directory,
  2. the `codex-claude-app` command (a two-line shell wrapper),
  3. the `claude_app_headless` stdio MCP server entry in Codex's config.toml.

Never overwrites or edits an existing file, skill folder, wrapper or MCP entry.
The config is only appended to; the parsed config is compared before and after
and the write is undone if any existing value would change. A timestamped
backup is kept next to the config. Standard library only; Python 3.11+.
"""
import argparse
import filecmp
import json
import os
from pathlib import Path
import shutil
import sys
import time

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

SKILL_NAME = 'claude-app-headless'
SERVER_NAME = 'claude_app_headless'
COMMAND_NAME = 'codex-claude-app'
SOURCE = Path(__file__).resolve().parent.parent
IGNORED = {'__pycache__', '.DS_Store'}


def identical(source, target):
    if not target.is_dir():
        return False
    for file in source.rglob('*'):
        if any(part in IGNORED for part in file.relative_to(source).parts) or not file.is_file():
            continue
        other = target / file.relative_to(source)
        if not other.is_file() or not filecmp.cmp(file, other, shallow=False):
            return False
    return True


def toml_string(value):
    return json.dumps(str(value))  # JSON string escaping is valid TOML basic-string escaping


def wrapper_text(python, script):
    return f'#!/bin/sh\nexec {sh_quote(python)} {sh_quote(script)} "$@"\n'


def sh_quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def mcp_block(python, script):
    return (f'\n[mcp_servers.{SERVER_NAME}]\n'
            f'command = {toml_string(python)}\n'
            f'args = [{toml_string(script)}, "mcp"]\n')


def plan(skills_dir, bin_dir, config, python):
    target = skills_dir / SKILL_NAME
    script = target / 'scripts' / 'claude_app_headless.py'
    wrapper = bin_dir / COMMAND_NAME
    actions = []
    if target.exists() or target.is_symlink():
        status = 'up-to-date' if identical(SOURCE, target) else 'skip-exists'
    else:
        status = 'create'
    actions.append(dict(kind='skill', status=status, path=str(target)))
    wanted = wrapper_text(python, script)
    if wrapper.exists() or wrapper.is_symlink():
        same = wrapper.is_file() and wrapper.read_text(errors='replace') == wanted
        actions.append(dict(kind='command', status='up-to-date' if same else 'skip-exists',
                            path=str(wrapper), content=wanted))
    else:
        actions.append(dict(kind='command', status='create', path=str(wrapper), content=wanted))
    block = mcp_block(python, script)
    if tomllib is None:
        actions.append(dict(kind='mcp', status='manual', path=str(config), content=block,
                            reason='Python 3.11+ is needed to verify the config merge'))
    else:
        current = {}
        if config.exists():
            try:
                current = tomllib.loads(config.read_text())
            except (tomllib.TOMLDecodeError, UnicodeError) as error:
                actions.append(dict(kind='mcp', status='manual', path=str(config), content=block,
                                    reason=f'existing config does not parse: {error}'))
                return actions
        existing = (current.get('mcp_servers') or {}).get(SERVER_NAME)
        if existing is not None:
            same = existing.get('command') == python and existing.get('args') == [str(script), 'mcp']
            actions.append(dict(kind='mcp', status='up-to-date' if same else 'skip-exists',
                                path=str(config), existing=existing))
        else:
            actions.append(dict(kind='mcp', status='append', path=str(config), content=block))
    return actions


def apply(actions):
    for action in actions:
        path = Path(action['path'])
        if action['kind'] == 'skill' and action['status'] == 'create':
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SOURCE, path, ignore=shutil.ignore_patterns(*IGNORED))
            action['done'] = True
        elif action['kind'] == 'command' and action['status'] == 'create':
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'x', encoding='utf-8') as handle:
                handle.write(action['content'])
            path.chmod(0o755)
            action['done'] = True
        elif action['kind'] == 'mcp' and action['status'] == 'append':
            append_verified(path, action['content'], action)
    return actions


def append_verified(config, block, action):
    before_text = config.read_text() if config.exists() else ''
    before = tomllib.loads(before_text)
    if config.exists():
        backup = config.with_name(config.name + '.bak-' + time.strftime('%Y%m%d%H%M%S'))
        shutil.copy2(config, backup)
        action['backup'] = str(backup)
    else:
        config.parent.mkdir(parents=True, exist_ok=True)
    separator = '' if not before_text or before_text.endswith('\n') else '\n'
    after_text = before_text + separator + block
    after = tomllib.loads(after_text)
    servers = dict(after.get('mcp_servers') or {})
    servers.pop(SERVER_NAME, None)
    expected = dict(after)
    if servers or 'mcp_servers' in before:
        expected['mcp_servers'] = servers
    else:
        expected.pop('mcp_servers', None)
    if expected != before:
        raise SystemExit('Refused: appending would change existing Codex config values. Nothing written.')
    with open(config, 'a', encoding='utf-8') as handle:
        handle.write(separator + block)
    if tomllib.loads(config.read_text()) != after:
        config.write_text(before_text)
        raise SystemExit('Refused: config changed during install; original restored.')
    action['done'] = True


def render(actions, applied):
    lines = ['Applied:' if applied else 'Preview (nothing written; add --apply):']
    labels = {'create': 'CREATE', 'append': 'APPEND', 'up-to-date': 'OK    ',
              'skip-exists': 'SKIP  ', 'manual': 'MANUAL'}
    for a in actions:
        lines.append(f"  {labels[a['status']]} {a['kind']:<8} {a['path']}")
    for a in actions:
        if a['status'] == 'skip-exists':
            lines.append(f"\nSKIP {a['kind']}: something different already exists at {a['path']}; "
                         'compare and update it yourself.')
        if a['status'] == 'manual':
            lines.append(f"\nMANUAL mcp: {a['reason']}. Add this block to {a['path']} yourself:\n{a['content']}")
        if a.get('backup'):
            lines.append(f"\nConfig backup: {a['backup']}")
    lines.append('\nNext: restart Codex, then run:  codex-claude-app list')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    home = Path.home()
    parser.add_argument('--skills-dir', type=Path, default=home / '.codex' / 'skills',
                        help='default ~/.codex/skills (the layout validated on 2026-10-19)')
    parser.add_argument('--bin-dir', type=Path, default=home / '.local' / 'bin')
    parser.add_argument('--codex-config', type=Path,
                        default=Path(os.environ.get('CODEX_HOME', home / '.codex')) / 'config.toml')
    parser.add_argument('--python', default=sys.executable, help='absolute interpreter for the bridge')
    parser.add_argument('--apply', action='store_true', help='write; default is preview only')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if not (SOURCE / 'SKILL.md').is_file():
        parser.exit(2, f'Skill source missing: {SOURCE}\n')
    if not os.path.isabs(args.python):
        parser.exit(2, '--python must be an absolute path\n')
    actions = plan(args.skills_dir.expanduser(), args.bin_dir.expanduser(),
                   args.codex_config.expanduser(), args.python)
    if args.apply:
        apply(actions)
    if args.json:
        print(json.dumps(dict(applied=args.apply, actions=actions), indent=2))
    else:
        print(render(actions, args.apply))
        if sys.platform != 'darwin':
            print('\nNote: the bridge itself runs only on macOS with Claude Desktop.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
