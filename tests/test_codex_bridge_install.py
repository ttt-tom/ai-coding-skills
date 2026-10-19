import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/claude-app-headless/scripts/install_codex.py'
spec = importlib.util.spec_from_file_location('install_codex', SCRIPT)
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)

EXISTING = '''model = "gpt-6"

[mcp_servers.other]
command = "/usr/bin/other"
args = ["serve"]
env = { TOKEN_NAME = "kept" }
'''


@unittest.skipIf(inst.tomllib is None, 'Python 3.11+ required for verified config merge')
class CodexBridgeInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / '.codex/config.toml'
        self.python = sys.executable

    def run_cli(self, *extra):
        out = io.StringIO()
        with redirect_stdout(out):
            code = inst.main(['--skills-dir', str(self.home / '.codex/skills'),
                              '--bin-dir', str(self.home / '.local/bin'),
                              '--codex-config', str(self.config),
                              '--python', self.python, '--json', *extra])
        self.assertEqual(code, 0)
        return {a['kind']: a for a in json.loads(out.getvalue())['actions']}

    def test_preview_writes_nothing(self):
        actions = self.run_cli()
        self.assertEqual({a['status'] for a in actions.values()}, {'create', 'append'})
        self.assertEqual(list(self.home.rglob('*')), [])

    def test_fresh_machine_install_and_command_runs(self):
        self.run_cli('--apply')
        skill = self.home / '.codex/skills/claude-app-headless'
        self.assertTrue((skill / 'SKILL.md').is_file())
        self.assertFalse(list(skill.rglob('__pycache__')))
        config = inst.tomllib.loads(self.config.read_text())
        server = config['mcp_servers']['claude_app_headless']
        self.assertEqual(server['command'], self.python)
        self.assertEqual(server['args'], [str(skill / 'scripts/claude_app_headless.py'), 'mcp'])
        wrapper = self.home / '.local/bin/codex-claude-app'
        self.assertTrue(wrapper.is_file())
        if sys.platform != 'win32':  # no executable bit on Windows; the bridge is macOS-only
            self.assertTrue(wrapper.stat().st_mode & 0o111)
            help_text = subprocess.run([str(wrapper), '--help'], capture_output=True, text=True, timeout=30)
            self.assertEqual(help_text.returncode, 0, help_text.stderr)
            self.assertIn('bind', help_text.stdout)

    def test_existing_config_values_are_preserved_and_backed_up(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text(EXISTING)
        before = inst.tomllib.loads(EXISTING)
        actions = self.run_cli('--apply')
        after = inst.tomllib.loads(self.config.read_text())
        self.assertEqual(after['model'], before['model'])
        self.assertEqual(after['mcp_servers']['other'], before['mcp_servers']['other'])
        self.assertTrue(self.config.read_text().startswith(EXISTING))
        self.assertEqual(Path(actions['mcp']['backup']).read_text(), EXISTING)

    def test_second_apply_is_idempotent(self):
        self.run_cli('--apply')
        snapshot = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file() and '.bak-' not in p.name}
        actions = self.run_cli('--apply')
        self.assertEqual({a['status'] for a in actions.values()}, {'up-to-date'})
        self.assertEqual(snapshot, {p: p.read_bytes() for p in snapshot})

    def test_existing_different_entries_are_never_modified(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text('[mcp_servers.claude_app_headless]\ncommand = "/elsewhere/python"\nargs = ["x", "mcp"]\n')
        wrapper = self.home / '.local/bin/codex-claude-app'
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text('#!/bin/sh\necho mine\n')
        skill = self.home / '.codex/skills/claude-app-headless'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('mine\n')
        before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        actions = self.run_cli('--apply')
        self.assertEqual({a['status'] for a in actions.values()}, {'skip-exists'})
        self.assertEqual(before, {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_unparseable_config_is_left_for_manual_merge(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text('not = [valid\n')
        actions = self.run_cli('--apply')
        self.assertEqual(actions['mcp']['status'], 'manual')
        self.assertEqual(self.config.read_text(), 'not = [valid\n')

    def test_relative_python_is_rejected(self):
        self.python = 'python3'
        with self.assertRaises(SystemExit):
            self.run_cli()


if __name__ == '__main__':
    unittest.main()
