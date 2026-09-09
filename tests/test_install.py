import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

SCRIPT = Path(__file__).resolve().parents[1] / 'install.py'
spec = importlib.util.spec_from_file_location('install', SCRIPT)
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'project'
        self.home = Path(self.temp.name).resolve() / 'home'
        self.root.mkdir()
        self.home.mkdir()

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = install.main(['--root', str(self.root), '--home', str(self.home), '--json', *args])
        return code, json.loads(out.getvalue())

    def tree(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*'))

    def test_preview_writes_nothing(self):
        code, data = self.run_cli('--client', 'all')
        self.assertEqual(code, 0)
        self.assertFalse(data['applied'])
        self.assertEqual(self.tree(), [])
        self.assertTrue(all(a['status'] == 'create' for a in data['actions']))

    def test_apply_dedupes_shared_dir_and_creates_pointers(self):
        _, data = self.run_cli('--client', 'all', '--apply')
        skills = [a['path'] for a in data['actions'] if a['kind'] == 'skill']
        self.assertEqual(len(skills), len(set(skills)))
        for rel in ('.agents/skills/efficient-code-maintenance/SKILL.md',
                    '.claude/skills/efficient-code-maintenance/SKILL.md',
                    '.windsurf/skills/efficient-code-maintenance/scripts/code_index.py',
                    'AGENTS.md', 'CLAUDE.md', 'GEMINI.md'):
            self.assertTrue((self.root / rel).is_file(), rel)
        self.assertEqual((self.root / 'CLAUDE.md').read_text(), '@AGENTS.md\n')
        self.assertIn(install.MARKER, (self.root / 'AGENTS.md').read_text())

    def test_second_apply_is_idempotent(self):
        self.run_cli('--client', 'all', '--apply')
        before = {p: (self.root / p).read_bytes() for p in self.tree() if (self.root / p).is_file()}
        _, data = self.run_cli('--client', 'all', '--apply')
        statuses = {a['status'] for a in data['actions']}
        self.assertEqual(statuses, {'up-to-date', 'suggest'})
        after = {p: (self.root / p).read_bytes() for p in self.tree() if (self.root / p).is_file()}
        self.assertEqual(before, after)

    def test_existing_rules_are_never_modified(self):
        (self.root / 'AGENTS.md').write_text('# mine\nkeep this\n')
        (self.root / 'CLAUDE.md').write_text('# claude\n')
        skill = self.root / '.agents/skills/efficient-code-maintenance'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('different\n')
        _, data = self.run_cli('--client', 'codex', '--client', 'claude-code', '--apply')
        by_path = {Path(a['path']).name: a for a in data['actions']}
        self.assertEqual(by_path['AGENTS.md']['status'], 'suggest')
        self.assertIn(install.MARKER, by_path['AGENTS.md']['snippet'])
        self.assertEqual(by_path['CLAUDE.md']['status'], 'suggest')
        self.assertEqual(by_path['efficient-code-maintenance']['status'], 'skip-exists')
        self.assertEqual((self.root / 'AGENTS.md').read_text(), '# mine\nkeep this\n')
        self.assertEqual((skill / 'SKILL.md').read_text(), 'different\n')

    def test_claude_only_creates_full_pointer_not_import(self):
        _, data = self.run_cli('--client', 'claude-code', '--apply')
        text = (self.root / 'CLAUDE.md').read_text()
        self.assertNotEqual(text, '@AGENTS.md\n')
        self.assertIn('.claude/skills/efficient-code-maintenance', text)
        self.assertFalse((self.root / 'AGENTS.md').exists())

    def test_user_scope_uses_home_and_writes_no_instructions(self):
        _, data = self.run_cli('--client', 'all', '--scope', 'user', '--apply')
        self.assertTrue(all(a['kind'] == 'skill' for a in data['actions']))
        for rel in ('.agents/skills', '.claude/skills', '.codeium/windsurf/skills', '.gemini/config/skills'):
            self.assertTrue((self.home / rel / 'efficient-code-maintenance/SKILL.md').is_file(), rel)
        self.assertEqual(self.tree(), [])

    @unittest.skipIf(sys.platform == 'win32', 'symlinks need privileges on Windows')
    def test_link_mode(self):
        _, data = self.run_cli('--client', 'zed', '--apply', '--link')
        target = self.root / '.agents/skills/efficient-code-maintenance'
        self.assertTrue(target.is_symlink())
        self.assertTrue((target / 'SKILL.md').is_file())

    def test_unknown_client_rejected(self):
        with self.assertRaises(SystemExit):
            self.run_cli('--client', 'nope')


if __name__ == '__main__':
    unittest.main()
