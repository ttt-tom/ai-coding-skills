#!/usr/bin/env python3
"""Local, tracked Python symbol index. No application imports or network calls."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

VERSION = 1
EXCLUDED = {'static', 'private_media', 'vendor', 'node_modules', '__pycache__'}


def sources(root):
    result = subprocess.run(['git', 'ls-files', '-z', '--', '*.py'], cwd=root,
                            capture_output=True, check=True)
    names = sorted(set(os.fsdecode(p) for p in result.stdout.split(b'\0') if p))
    selected = []
    for name in names:
        path = Path(name)
        if any(part.startswith('.') or part in EXCLUDED for part in path.parts):
            continue
        full = root / path
        if path.is_absolute() or '..' in path.parts or full.resolve() != full.absolute():
            raise ValueError('Unsafe source path')
        selected.append(name)
    return selected


def snapshot(root):
    return {name: (root / name).read_bytes() for name in sources(root)}


def hashes(contents):
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()}


class Visitor(ast.NodeVisitor):
    def __init__(self, path):
        self.path, self.scope, self.items = path, [], []

    def visit_ClassDef(self, node):
        self.record(node, 'class')

    def visit_FunctionDef(self, node):
        self.record(node, 'function')

    def visit_AsyncFunctionDef(self, node):
        self.record(node, 'async_function')

    def record(self, node, kind):
        name = '.'.join(self.scope + [node.name])
        calls = set()
        if kind != 'class':
            # Includes nested scopes: deliberately a candidate relation only.
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.add(child.func.attr)
        self.items.append(dict(id=f'{self.path}::{name}@{node.lineno}', name=name,
                               file=self.path, start=node.lineno, end=node.end_lineno,
                               kind=kind, candidate_calls=sorted(calls)))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def build(root):
    contents = snapshot(root)
    symbols = []
    for name, raw in contents.items():
        try:
            tree = ast.parse(raw, filename=name)
        except SyntaxError as exc:
            raise ValueError(f'Parse failed: {name}:{exc.lineno}; old index preserved') from None
        visitor = Visitor(name)
        visitor.visit(tree)
        symbols.extend(visitor.items)
    data = dict(version=VERSION, hashes=hashes(contents), symbols=symbols)
    folder = root / '.code-index'
    if folder.is_symlink():
        raise ValueError('Index directory must not be a symlink')
    folder.mkdir(exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder,
                                         delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, folder / 'symbols.json')
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return data


def load_fresh(root):
    data = json.loads((root / '.code-index/symbols.json').read_text(encoding='utf-8'))
    if data.get('version') != VERSION or data.get('hashes') != hashes(snapshot(root)):
        raise ValueError('Index stale; run build before query')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'check', 'query'])
    parser.add_argument('symbol', nargs='?')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        data = build(root) if args.action == 'build' else load_fresh(root)
        if args.action == 'query':
            if not args.symbol:
                parser.error('query requires a symbol')
            matches = [s for s in data['symbols'] if args.symbol in s['name'] or args.symbol == s['id']]
            for item in matches[:20]:
                print(f"{item['id']} [{item['start']}-{item['end']}]")
                print('  candidate calls:', ', '.join(item['candidate_calls'][:12]))
            print(f'{len(matches)} matches; showing at most 20; no runtime resolution implied')
        else:
            print(f"OK: {len(data['hashes'])} files, {len(data['symbols'])} symbols")
    except (OSError, ValueError, subprocess.CalledProcessError):
        # Avoid exposing malformed source snippets or Git diagnostics.
        parser.exit(1, 'Index operation failed: check Git root, source syntax and freshness; rebuild if stale.\n')


if __name__ == '__main__':
    main()
