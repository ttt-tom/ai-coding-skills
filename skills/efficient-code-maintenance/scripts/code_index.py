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

VERSION = 2
EXCLUDED = {'vendor', 'node_modules', '__pycache__'}


def sources(root, exclude=()):
    result = subprocess.run(['git', 'ls-files', '-z', '--', '*.py'], cwd=root,
                            capture_output=True, check=True)
    names = sorted(set(os.fsdecode(p) for p in result.stdout.split(b'\0') if p))
    selected = []
    for name in names:
        path = Path(name)
        full = root / path
        if path.is_absolute() or '..' in path.parts or full.resolve() != full.absolute():
            raise ValueError('Unsafe source path')
        if any(part.startswith('.') or part in EXCLUDED or part in exclude for part in path.parts):
            continue
        selected.append(name)
    return selected


def snapshot(root, exclude=()):
    return {name: (root / name).read_bytes() for name in sources(root, exclude)}


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


def build(root, exclude=()):
    contents = snapshot(root, exclude)
    symbols = []
    for name, raw in contents.items():
        try:
            tree = ast.parse(raw, filename=name)
        except SyntaxError as exc:
            raise ValueError(f'Parse failed: {name}:{exc.lineno}; old index preserved') from None
        visitor = Visitor(name)
        visitor.visit(tree)
        symbols.extend(visitor.items)
    callers = {}
    for symbol in symbols:
        for callee in symbol['candidate_calls']:
            callers.setdefault(callee, []).append(symbol['id'])
    data = dict(version=VERSION, hashes=hashes(contents), symbols=symbols,
                callers=callers, exclude=sorted(set(exclude)))
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


def load_fresh(root, exclude=()):
    data = json.loads((root / '.code-index/symbols.json').read_text(encoding='utf-8'))
    if data.get('version') != VERSION or data.get('exclude') != sorted(set(exclude)) or data.get('hashes') != hashes(snapshot(root, exclude)):
        raise ValueError('Index stale; run build before query')
    return data


def query(data, name, callers=False):
    exact = [s for s in data['symbols'] if name in (s['id'], s['name'], s['name'].rsplit('.', 1)[-1])]
    matches = exact or [s for s in data['symbols'] if name in s['name']]
    if not callers:
        return matches
    names = {s['name'].rsplit('.', 1)[-1] for s in matches} or {name}
    ids = {caller for key in names for caller in data['callers'].get(key, [])}
    return [s for s in data['symbols'] if s['id'] in ids]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'check', 'query'])
    parser.add_argument('symbol', nargs='?')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--callers', action='store_true', help='Find candidate callers instead of definitions')
    parser.add_argument('--json', action='store_true', dest='as_json', help='Emit one JSON object on stdout; errors remain on stderr')
    parser.add_argument('--file', metavar='PATH', help='Restrict query results to this exact repository-relative file')
    parser.add_argument('--exclude', action='append', default=[], metavar='DIRECTORY', help='Exclude a directory component; repeatable, pass consistently on each command')
    parser.add_argument('--rebuild', action='store_true', help='On query, rebuild missing or stale index before answering')
    args = parser.parse_args()
    if args.file and args.action != 'query':
        parser.error('--file requires query')
    root = args.root.resolve()
    try:
        if args.action == 'query' and not args.symbol:
            parser.error('query requires a symbol')
        try:
            data = build(root, args.exclude) if args.action == 'build' else load_fresh(root, args.exclude)
        except (FileNotFoundError, ValueError):
            if args.action != 'query' or not args.rebuild:
                raise
            data = build(root, args.exclude)
        if args.action == 'query':
            matches = query(data, args.symbol, args.callers)
            if args.file:
                matches = [s for s in matches if s['file'] == args.file]
            warning = ('Broad name: many candidate callers. Use --file PATH to narrow results; '
                       'class prefixes do not resolve bare-name ambiguity.') if args.callers and len(matches) > 20 else None
            results = [{k: v for k, v in item.items() if not args.callers or k != 'candidate_calls'} for item in matches[:20]]
            if args.as_json:
                print(json.dumps(dict(schema_version=1, query=args.symbol,
                    mode='callers' if args.callers else 'definitions', total=len(matches),
                    truncated=len(matches) > 20, warning=warning, results=results), ensure_ascii=True))
            else:
                for item in results:
                    print(f"{item['id']} [{item['start']}-{item['end']}]")
                    if not args.callers:
                        print('  candidate calls:', ', '.join(item['candidate_calls'][:12]))
                print(f'{len(matches)} matches; showing at most 20; no runtime resolution implied')
                if warning:
                    print(warning)
        else:
            if args.as_json:
                print(json.dumps(dict(schema_version=1, status='ok', files=len(data['hashes']), symbols=len(data['symbols']))))
            else:
                print(f"OK: {len(data['hashes'])} files, {len(data['symbols'])} symbols")
    except subprocess.CalledProcessError:
        parser.exit(1, 'Git source enumeration failed; check repository root.\n')
    except json.JSONDecodeError:
        parser.exit(1, 'Invalid index JSON; rebuild required.\n')
    except ValueError as exc:
        parser.exit(1, str(exc) + '\n')
    except OSError as exc:
        parser.exit(1, f'Filesystem error: {exc.strerror}; path={exc.filename}\n')


if __name__ == '__main__':
    main()
