"""Regression tests for the text-first worklog guard, the stop-gate write
detection and search freshness (fix round 4)."""
import os
import sys
import unittest
from unittest import mock

from helpers import FakeHome
from jarvan_memory import hooks, installer, search, util

STAMP = "2026-11-11 10:00"


class TextFirstRuleTest(unittest.TestCase):
    def setUp(self):
        self.h = FakeHome()
        self.env = mock.patch.dict(os.environ, self.h.env)
        self.env.start()
        self.cfg = {"vault": str(self.h.vault), "mem_cmd": "mem", "modules": []}
        installer.build_vault(self.cfg, {})
        util.save_config(self.cfg)
        self.wl = (self.h.vault / "worklog").as_posix()
        self.outside = self.h.work.as_posix()

    def tearDown(self):
        self.env.stop()
        self.h.cleanup()

    def bash(self, command):
        return {"tool_name": "Bash", "cwd": str(self.h.work), "tool_input": {"command": command}}

    def denied(self, command):
        return hooks.guard_reason(self.bash(command), self.cfg) is not None

    def test_heredoc_with_an_apostrophe_writing_a_timestamp_is_denied(self):
        command = f"cat >> {self.wl}/a.md <<'EOF'\nit's {STAMP} done\nEOF"
        self.assertTrue(self.denied(command))
        self.assertTrue(self.denied(f"cat <<EOF > {self.outside}/x.md\n{STAMP} worklog\nEOF"))

    def test_opaque_forms_are_denied_only_with_worklog_and_a_timestamp(self):
        for form in ('echo "{s} worklog" >> "$(echo x).md"', "echo `date` '{s} worklog' > x.md",
                     "eval 'echo {s} worklog > x'", "bash -c 'echo {s} worklog > x'",
                     "python3 -c 'print(1)' # {s} worklog", "echo '{s} worklog' | xargs tee",
                     "env -i tee x # {s} worklog"):
            command = form.format(s=STAMP)
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertFalse(self.denied(command.replace("worklog", "log")))
                self.assertFalse(self.denied(command.replace(STAMP, "now")))

    def test_comment_mentioning_worklog_is_allowed_when_the_target_resolves_outside(self):
        self.assertFalse(self.denied(f"printf '{STAMP}' > {self.outside}/x.md # worklog"))
        self.assertTrue(self.denied(f"printf '{STAMP}' > {self.wl}/x.md"))

    def test_command_without_a_write_target_is_allowed(self):
        self.assertFalse(self.denied(f'git commit -m "fix worklog {STAMP}"'))

    def test_unresolvable_variable_target_is_denied_and_prefix_assignment_is_scoped(self):
        self.assertTrue(self.denied(
            f'export D="{self.h.vault.as_posix()}"; echo "{STAMP}" >> "$D/worklog/e.md"'))
        self.assertTrue(self.denied(
            f'D="{self.h.vault.as_posix()}"; echo "{STAMP}" >> "${{D:-.}}/worklog/d.md"'))
        # The redirection is expanded by the shell, without the prefix assignment.
        command = f'D="{self.h.vault.as_posix()}" echo "{STAMP}" >> "$D/worklog/a.md"'
        with mock.patch.dict(os.environ, {"D": self.outside}):
            self.assertFalse(self.denied(command))

    def test_parser_failure_is_denied(self):
        with mock.patch.object(hooks, "bash_writes", side_effect=ValueError("boom")):
            self.assertTrue(self.denied(f"echo '{STAMP}' > {self.outside}/worklog.md"))

    def test_stop_gate_counts_mem_writes_anywhere_in_the_text(self):
        for command in ("sudo mem log x", "if true; then mem log x; fi", "VAR=1 mem log x",
                        "cat <<EOF\nmem log x\nEOF", 'echo "mem verify claim"', "mem.cmd log x"):
            with self.subTest(command=command):
                self.assertTrue(hooks.touches_vault(self.bash(command), self.cfg))
        for command in ("mem list x", "git log x", "xmem log x", "echo mem"):
            with self.subTest(command=command):
                self.assertFalse(hooks.touches_vault(self.bash(command), self.cfg))

    def test_stop_gate_counts_the_configured_launcher_path(self):
        launcher = (self.h.app / "bin" / "custom-mem").as_posix()
        cfg = dict(self.cfg, mem_cmd=launcher)
        self.assertTrue(hooks.touches_vault(self.bash(f'"{launcher}" log x'), cfg))
        self.assertTrue(hooks.touches_vault(self.bash(f"{launcher} handoff close s"), cfg))

    def test_stop_gate_survives_a_parser_failure(self):
        with mock.patch.object(hooks, "bash_writes", side_effect=ValueError("boom")):
            self.assertTrue(hooks.touches_vault(self.bash("mem log x"), self.cfg))
            self.assertFalse(hooks.touches_vault(self.bash("ls"), self.cfg))


class SearchFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.h = FakeHome()
        self.env = mock.patch.dict(os.environ, self.h.env)
        self.env.start()
        self.cfg = {"vault": str(self.h.vault), "mem_cmd": "mem", "modules": []}
        installer.build_vault(self.cfg, {})
        util.save_config(self.cfg)
        self.topics = self.h.vault / "topics"

    def tearDown(self):
        self.env.stop()
        self.h.cleanup()

    def find(self, query):
        return [r["path"] for r in search.search(query, root=self.h.vault, cfg=self.cfg,
                                                 budget=search.HOOK_INDEX_BUDGET)]

    def test_a_refuted_oversized_note_is_not_returned_with_its_old_status(self):
        note = self.topics / "Decision.md"
        note.write_text("---\nstatus: verified\n---\n# Decision\n\nnebula cobalt zircon\n",
                        encoding="utf-8")
        self.assertIn("topics/Decision.md", self.find("nebula cobalt zircon"))
        note.write_text("---\nstatus: refuted\n---\n# Decision\n\nrefuted\n" +
                        "unrelated padding\n" * 40000, encoding="utf-8")
        self.assertGreater(note.stat().st_size, search.HOOK_MAX_NOTE_BYTES)
        self.assertNotIn("topics/Decision.md", self.find("nebula cobalt zircon"))

    def test_a_changed_note_whose_reindex_is_deferred_by_the_budget_loses_its_rows(self):
        note = self.topics / "Changed.md"
        note.write_text("# Changed\n\nzebrafish original marker\n", encoding="utf-8")
        self.assertIn("topics/Changed.md", self.find("zebrafish original marker"))
        note.write_text("# Changed\n\nzebrafish original marker edited\n", encoding="utf-8")
        con = search.update_index(self.h.vault, self.cfg, budget=0)
        try:
            self.assertEqual(con.execute(
                "SELECT count(*) FROM sections WHERE path='topics/Changed.md'").fetchone()[0], 0)
            self.assertFalse(search.is_complete(con))
        finally:
            con.close()

    def test_a_deleted_note_is_gone_from_hook_search_while_another_file_is_deferred(self):
        gone = self.topics / "Gone.md"
        gone.write_text("# Gone\n\nzebrafish vanishing marker\n", encoding="utf-8")
        self.assertIn("topics/Gone.md", self.find("zebrafish vanishing marker"))
        gone.unlink()
        (self.topics / "Huge.md").write_text("# Huge\n\n" + "padding line\n" * 60000,
                                             encoding="utf-8")
        self.assertNotIn("topics/Gone.md", self.find("zebrafish vanishing marker"))


if __name__ == "__main__":
    unittest.main()
