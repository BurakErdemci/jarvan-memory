"""Regression tests for fix round 5: search freshness while the index is busy,
the worklog guard trigger (a path, not a word), interpreter flag and cp -t
coverage, the linear opaque-form regex, and the installed hook runtime."""
import os
import sqlite3
import time
import unittest
from unittest import mock

from helpers import BASH, FakeHome
from jarvan_memory import hooks, installer, search, util

STAMP = "2026-11-11 10:00"


class GuardTriggerTest(unittest.TestCase):
    def setUp(self):
        self.h = FakeHome()
        self.env = mock.patch.dict(os.environ, self.h.env)
        self.env.start()
        self.cfg = {"vault": str(self.h.vault), "mem_cmd": "mem", "modules": []}
        installer.build_vault(self.cfg, {})
        util.save_config(self.cfg)
        self.wl = (self.h.vault / "worklog").as_posix()

    def tearDown(self):
        self.env.stop()
        self.h.cleanup()

    def reason(self, command):
        return hooks.guard_reason({"tool_name": "Bash", "cwd": str(self.h.work),
                                   "tool_input": {"command": command}}, self.cfg)

    def denied(self, command):
        return self.reason(command) is not None

    def test_ordinary_project_commands_that_mention_the_word_are_allowed(self):
        for command in (f"cat > notes.md <<EOF\nmeeting {STAMP} worklog review\nEOF",
                        f"git commit -m 'use `mem log` for worklog {STAMP}'",
                        f'sed -i "s/..10:30$/X/" CHANGELOG.md # {STAMP} worklog',
                        f'echo "{STAMP} worklog" > out$1.txt',
                        f"bash -c 'echo {STAMP} worklog > x.md'"):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))

    def test_a_worklog_path_reference_keeps_the_opaque_rule(self):
        self.assertTrue(self.denied(f"cat > notes.md <<EOF\n{STAMP} worklog/a.md\nEOF"))
        self.assertTrue(self.denied(f"cat > notes.md <<EOF\n{self.wl}\n{STAMP}\nEOF"))
        self.assertTrue(self.denied(f"cat > notes.md <<EOF\n{self.wl}\n{STAMP}\nEOF".replace("/", "\\")))
        self.assertTrue(self.denied(f"cd {self.h.vault.as_posix()} && cp x.md worklog # {STAMP}"))
        self.assertTrue(self.denied(f"cd $V && cp x.md worklog # {STAMP}"))

    def test_joined_and_shell_specific_interpreter_flags_are_opaque(self):
        for form in ("bash -lc 'echo {s} > worklog/a.md'", "bash -ec 'echo {s} > worklog/a.md'",
                     "bash -c'echo {s} > worklog/a.md'", 'python3 -c"print(1)" # {s} worklog/a.md',
                     "powershell -Command \"Add-Content worklog/a.md '{s}'\"",
                     "pwsh -c \"Add-Content worklog/a.md '{s}'\"", "cmd /c echo {s} >> worklog\\a.md",
                     "C:/Python/python.exe -c 'echo {s} worklog/a.md'", "'C:/Program Files/Python/python.exe' -c 'echo {s} worklog/a.md'"):
            command = form.format(s=STAMP)
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_cp_target_directory_is_a_write_target(self):
        for option in (f"-t {self.wl}", f"--target-directory {self.wl}", f"--target-directory={self.wl}",
                       f"-at {self.wl}"):
            command = f"cp {option} entry.md # {STAMP}"
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
        self.assertFalse(self.denied(f"cp -t {self.h.work.as_posix()} entry.md # {STAMP} {self.wl}"))

    def test_deny_message_names_the_reason(self):
        self.assertIn("could not be verified", self.reason(f"eval 'echo {STAMP}' # worklog/a.md"))
        self.assertNotIn("could not be verified", self.reason(f"echo '{STAMP}' >> {self.wl}/a.md"))
        self.assertIn("append-only", self.reason(f"echo '{STAMP}' >> {self.wl}/a.md"))

    def test_the_opaque_regex_is_linear_on_a_long_line(self):
        command = f"echo {STAMP} worklog/a.md " + "sh " * 30000
        started = time.time()
        self.denied(command)
        self.assertLess(time.time() - started, 0.5)


class BusyIndexFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.h = FakeHome()
        self.env = mock.patch.dict(os.environ, self.h.env)
        self.env.start()
        self.vault = self.h.vault
        (self.vault / "topics").mkdir(parents=True)
        self.cfg = {"vault": str(self.vault), "mem_cmd": "mem", "modules": []}
        self.note = self.vault / "topics" / "Decision.md"
        self.note.write_text("---\nstatus: verified\n---\n# Decision\n\nnebula cobalt zircon\n", encoding="utf-8")

    def tearDown(self):
        self.env.stop()
        self.h.cleanup()

    def paths(self):
        return [r["path"] for r in search.search("nebula cobalt zircon", root=self.vault, cfg=self.cfg, budget=3.0)]

    def hold_lock(self):
        con = sqlite3.connect(str(search.db_path(self.vault)), timeout=0.1)
        con.execute("BEGIN IMMEDIATE")
        return con

    def test_a_deleted_note_is_not_returned_while_the_index_is_locked(self):
        self.assertEqual(self.paths(), ["topics/Decision.md"])
        self.note.unlink()
        lock = self.hold_lock()
        try:
            self.assertEqual(self.paths(), [])
        finally:
            lock.rollback()
            lock.close()

    def test_a_changed_note_is_not_returned_with_its_old_status_while_locked(self):
        self.assertEqual(self.paths(), ["topics/Decision.md"])
        self.note.write_text("---\nstatus: refuted\n---\n# Decision\n\nnebula cobalt zircon and more\n",
                             encoding="utf-8")
        lock = self.hold_lock()
        try:
            self.assertEqual(self.paths(), [])
        finally:
            lock.rollback()
            lock.close()
        self.assertEqual([r["status"] for r in search.search(
            "nebula cobalt zircon", root=self.vault, cfg=self.cfg, budget=3.0)], ["refuted"])


@unittest.skipUnless(BASH, "bash not found")
class InstalledRuntimeTest(unittest.TestCase):
    """The registered hook command runs the installed copy of the runtime,
    not the repository modules the other tests import."""

    def setUp(self):
        self.h = FakeHome()
        self.h.install("--name", "Ada", "--modules", "none", "--no-doctor")

    def tearDown(self):
        self.h.cleanup()

    def test_the_installed_pre_tool_hook_refuses_a_typed_worklog_timestamp(self):
        reply = self.h.hook("pre-tool", {"tool_name": "Bash", "tool_input": {
            "command": f"bash -lc 'echo {STAMP} >> {self.h.vault.as_posix()}/worklog/a.md'"}})
        self.assertIsNotNone(reply)
        self.assertEqual(reply["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(self.h.hook("pre-tool", {"tool_name": "Bash", "tool_input": {
            "command": f"cat > notes.md <<EOF\nreview {STAMP} worklog\nEOF"}}))

    def test_the_installed_prompt_hook_drops_a_note_deleted_while_the_index_is_locked(self):
        note = self.h.vault / "topics" / "Decision.md"
        note.write_text("---\nstatus: verified\n---\n# Decision\n\nnebula cobalt zircon\n", encoding="utf-8")
        prompt = {"prompt": "nebula cobalt zircon"}
        warm = self.h.mem("search", "nebula cobalt zircon")
        self.assertIn("[verified]", warm.stdout)
        note.unlink()
        db = next((self.h.app / "state").glob("search-*.sqlite"))
        lock = sqlite3.connect(str(db), timeout=1)
        lock.execute("BEGIN IMMEDIATE")
        try:
            reply = self.h.hook("user-prompt", dict(prompt, session_id="busy"))
        finally:
            lock.rollback()
            lock.close()
        text = ((reply or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")
        self.assertNotIn("nebula cobalt zircon", text)


if __name__ == "__main__":
    unittest.main()
