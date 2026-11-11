"""Install / uninstall promises: idempotent, foreign settings preserved,
uninstall restores what was there before."""
import json
import unittest

from helpers import BASH, FakeHome

FOREIGN = {
    "model": "sonnet",
    "permissions": {"allow": ["Bash(ls:*)"]},
    "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "echo user-stop"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "user-guard.sh"}]}],
    },
}


@unittest.skipUnless(BASH, "bash not found")
class InstallTest(unittest.TestCase):
    def setUp(self):
        self.h = FakeHome()

    def tearDown(self):
        self.h.cleanup()

    def _ours(self):
        data = json.loads(self.h.settings.read_text(encoding="utf-8"))
        return sum(1 for groups in data["hooks"].values() for g in groups
                   for x in g["hooks"] if "jarvan-memory/hook.sh" in x["command"])

    def test_hooks_find_their_install_without_the_install_env(self):
        # Claude Code can start without the CLAUDE_CONFIG_DIR/HOME the
        # installer saw; the hook must still find its own config.
        self.h.install("--modules", "none", "--no-doctor")
        elsewhere = self.h.root / "other-home"
        elsewhere.mkdir()
        self.h.env.pop("CLAUDE_CONFIG_DIR")
        self.h.env.update({"HOME": str(elsewhere), "USERPROFILE": str(elsewhere)})
        out = self.h.hook("session-start", {"hook_event_name": "SessionStart", "source": "startup"})
        text = json.dumps(out)
        self.assertNotIn("not installed", text)
        self.assertIn("jarvan-memory", text)

    def test_install_twice_is_idempotent(self):
        self.h.install("--modules", "none", "--no-doctor")
        first_settings = self.h.settings.read_text(encoding="utf-8")
        first_md = (self.h.claude / "CLAUDE.md").read_text(encoding="utf-8")
        self.h.install("--modules", "none", "--no-doctor")
        self.assertEqual(self._ours(), 7)
        self.assertEqual(json.loads(self.h.settings.read_text(encoding="utf-8")),
                         json.loads(first_settings))
        md = (self.h.claude / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(md, first_md)
        self.assertEqual(md.count("jarvan-memory:begin"), 1)

    def test_merge_preserves_foreign_hooks_and_keys(self):
        self.h.claude.mkdir(parents=True)
        self.h.settings.write_text(json.dumps(FOREIGN), encoding="utf-8")
        self.h.install("--modules", "none", "--no-doctor")
        data = json.loads(self.h.settings.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "sonnet")
        self.assertEqual(data["permissions"], FOREIGN["permissions"])
        cmds = [x["command"] for g in data["hooks"]["Stop"] for x in g["hooks"]]
        self.assertIn("echo user-stop", cmds)
        cmds = [x["command"] for g in data["hooks"]["PreToolUse"] for x in g["hooks"]]
        self.assertIn("user-guard.sh", cmds)
        backups = list(self.h.claude.glob("settings.json.jarvan-memory-*.bak"))
        self.assertEqual(len(backups), 1)

    def test_uninstall_restores_settings_and_claude_md_bytes(self):
        self.h.claude.mkdir(parents=True)
        original = json.dumps(FOREIGN, indent=4)
        self.h.settings.write_text(original, encoding="utf-8")
        md_original = "# My rules\r\n\r\nBe brief.\r\n"
        (self.h.claude / "CLAUDE.md").write_bytes(md_original.encode("utf-8"))
        self.h.install("--modules", "none", "--no-doctor")
        self.h.install("--modules", "none", "--no-doctor")
        r = self.h.mem("uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.h.settings.read_text(encoding="utf-8"), original)
        self.assertEqual((self.h.claude / "CLAUDE.md").read_bytes(), md_original.encode("utf-8"))
        self.assertFalse(self.h.app.exists())
        self.assertEqual(list(self.h.claude.glob("*.bak")), [])
        self.assertTrue((self.h.vault / "AGENT.md").exists(), "vault must be kept")

    def test_uninstall_removes_files_it_created(self):
        self.h.install("--modules", "none", "--no-doctor")
        self.h.mem("uninstall")
        self.assertFalse(self.h.settings.exists())
        self.assertFalse((self.h.claude / "CLAUDE.md").exists())

    def test_uninstall_keeps_settings_changed_after_install(self):
        self.h.install("--modules", "none", "--no-doctor")
        data = json.loads(self.h.settings.read_text(encoding="utf-8"))
        data["theme"] = "dark"
        self.h.settings.write_text(json.dumps(data), encoding="utf-8")
        self.h.mem("uninstall")
        self.assertEqual(json.loads(self.h.settings.read_text(encoding="utf-8")), {"theme": "dark"})

    def test_invalid_settings_is_never_overwritten(self):
        self.h.claude.mkdir(parents=True)
        self.h.settings.write_text("{ not json", encoding="utf-8")
        r = self.h.install("--modules", "none", "--no-doctor", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.h.settings.read_text(encoding="utf-8"), "{ not json")

    def test_existing_vault_notes_are_kept(self):
        self.h.vault.mkdir(parents=True)
        (self.h.vault / "AGENT.md").write_text("my own contract", encoding="utf-8")
        self.h.install("--modules", "none", "--no-doctor")
        self.assertEqual((self.h.vault / "AGENT.md").read_text(encoding="utf-8"), "my own contract")
        self.assertTrue((self.h.vault / "INDEX.md").exists())


if __name__ == "__main__":
    unittest.main()
