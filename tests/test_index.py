import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
import shutil
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/efficient-code-maintenance/scripts/code_index.py'
spec = importlib.util.spec_from_file_location('index', SCRIPT)
index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def source(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        subprocess.run(['git', 'add', '--', name], cwd=self.root, check=True)

    def test_collision_privacy_and_no_import(self):
        self.source('a.py', 'raise RuntimeError("NO_IMPORT")\ndef main(key="SECRET"):\n return "BODY"\ndef main(): pass')
        self.source('b.py', 'def main(): pass')
        data = index.build(self.root)
        self.assertEqual(len({s['id'] for s in data['symbols']}), 3)
        self.assertNotIn('SECRET', json.dumps(data))
        self.assertNotIn('BODY', json.dumps(data))

    def test_stale_and_failed_build_preserves_index(self):
        self.source('a.py', 'def f(): pass')
        index.build(self.root)
        index.load_fresh(self.root)
        old = (self.root / '.code-index/symbols.json').read_bytes()
        (self.root / 'a.py').write_text('def broken(')
        with self.assertRaises(ValueError): index.load_fresh(self.root)
        with self.assertRaises(ValueError): index.build(self.root)
        self.assertEqual(old, (self.root / '.code-index/symbols.json').read_bytes())

    def test_excluded_and_untracked(self):
        self.source('static/private.py', 'def secret(): pass')
        (self.root / 'untracked.py').write_text('def hidden(): pass')
        self.assertEqual(index.build(self.root, ['static'])['symbols'], [])
        self.assertEqual(len(index.build(self.root)['symbols']), 1)

    def test_file_set_change(self):
        self.source('a.py', 'def f(): pass')
        index.build(self.root)
        self.source('b.py', 'def g(): pass')
        with self.assertRaises(ValueError): index.load_fresh(self.root)

    def test_missing_tracked_source(self):
        self.source('a.py', 'def f(): pass')
        index.build(self.root)
        (self.root / 'a.py').unlink()
        with self.assertRaises(OSError): index.load_fresh(self.root)

    def test_query_exact_fuzzy_and_callers(self):
        self.source('a.py', 'def snapshot(): pass\ndef snapshot_extra(): pass\ndef consumer(): snapshot()')
        data = index.build(self.root)
        self.assertEqual([s['name'] for s in index.query(data, 'snapshot')], ['snapshot'])
        self.assertEqual(len(index.query(data, 'snap')), 2)
        self.assertEqual([s['name'] for s in index.query(data, 'snapshot', True)], ['consumer'])
        self.assertEqual(index.query(data, 'absent'), [])

    def test_unsafe_source_paths(self):
        for name in ['../escape.py', str(self.root / 'absolute.py')]:
            with patch.object(index.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=os.fsencode(name) + b'\0')):
                with self.assertRaisesRegex(ValueError, 'Unsafe source path'):
                    index.sources(self.root)

    def test_cli_rebuild_and_parse_diagnostic(self):
        self.source('a.py', 'def snapshot(): pass')
        cmd = [sys.executable, str(SCRIPT), 'query', 'snapshot', '--root', str(self.root), '--rebuild']
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('snapshot', result.stdout)
        (self.root / 'a.py').write_text('\n\ndef snapshot(): pass')
        self.assertIn('@3', subprocess.run(cmd, capture_output=True, text=True).stdout)
        (self.root / 'a.py').write_text('def broken( # PRIVATE_MARKER')
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('a.py:1', result.stderr)
        self.assertNotIn('PRIVATE_MARKER', result.stderr)

    def test_standalone_skill_copy(self):
        copied = self.root / 'installed-skill'
        shutil.copytree(SCRIPT.parents[1], copied)
        for name in ['AGENTS.md', 'PROJECT.md', 'CODEMAP.md', 'ACTIVE_HANDOFF.md']:
            self.assertTrue((copied / 'templates' / name).is_file())
        self.source('a.py', 'def snapshot(): pass')
        result = subprocess.run([sys.executable, str(copied / 'scripts/code_index.py'), 'query', 'snapshot', '--root', str(self.root), '--rebuild'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('snapshot', result.stdout)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args, '--root', str(self.root)], capture_output=True, text=True)

    def test_json_callers_filter_and_empty_output(self):
        self.source('a.py', 'def snapshot(): pass\ndef caller(): snapshot()')
        self.source('b.py', 'def another(): snapshot()')
        result = self.cli('query', 'snapshot', '--callers', '--rebuild', '--json', '--file', 'b.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['total'], 1)
        self.assertFalse(payload['truncated'])
        self.assertEqual(payload['results'][0]['name'], 'another')
        self.assertNotIn('candidate_calls', payload['results'][0])
        empty = json.loads(self.cli('query', 'absent', '--json').stdout)
        self.assertEqual(empty['results'], [])
        text = self.cli('query', 'snapshot', '--callers').stdout
        self.assertNotIn('candidate calls:', text)

    def test_json_truncation_warning(self):
        self.source('a.py', '\n'.join(f'def c{i}(): obj.get()' for i in range(21)))
        payload = json.loads(self.cli('query', 'get', '--callers', '--rebuild', '--json').stdout)
        self.assertEqual(payload['total'], 21)
        self.assertEqual(len(payload['results']), 20)
        self.assertTrue(payload['truncated'])
        self.assertIn('--file', payload['warning'])

    def test_json_build_check_and_error_channels(self):
        self.source('a.py', 'def f(): pass')
        for action in ['build', 'check']:
            self.assertEqual(json.loads(self.cli(action, '--json').stdout)['status'], 'ok')
        (self.root / 'a.py').write_text('def broken(')
        result = self.cli('query', 'f', '--rebuild', '--json')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('a.py:1', result.stderr)

    def test_ignore_snippet_excludes_private_data_not_shared_rules(self):
        snippet = SCRIPT.parents[1] / 'templates/gitignore-ai.txt'
        (self.root / '.gitignore').write_text(snippet.read_text(encoding='utf-8'), encoding='utf-8')
        private = ['.env', '.env.production', '.claude/settings.local.json',
                   '.claude/worktrees/session/file.py', '.gemini/oauth_creds.json',
                   '.gemini/antigravity/brain/task/log.txt', '.antigravity/sessions/session.json',
                   '.cursor/cache/state.json', '.zed/settings.local.json', '.codex/auth.json']
        shared = ['.env.example', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md',
                  '.claude/skills/demo/SKILL.md', '.gemini/skills/demo/SKILL.md',
                  '.cursor/rules/maintenance.mdc', '.agent/rules/maintenance.md',
                  '.agents/skills/demo/SKILL.md', '.zed/settings.json',
                  '.github/copilot-instructions.md']
        for path in private + shared:
            result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', '--', path], cwd=self.root)
            self.assertEqual(result.returncode, 0 if path in private else 1, path)
