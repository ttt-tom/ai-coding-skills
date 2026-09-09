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
