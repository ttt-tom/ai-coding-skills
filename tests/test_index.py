import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

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
        self.assertEqual(index.build(self.root)['symbols'], [])

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
