"""`mem` write-path promises: binary carry-over declaration, line budget,
handoffs derived from their own status, promotion gate, refuted records
kept, duplicate-name refusal."""
import re
import unittest

from helpers import HomeTest


class MemTest(HomeTest):
    def ok(self, *args):
        r = self.h.mem(*args)
        self.assertEqual(r.returncode, 0, f"{args}: {r.stderr}")
        return r.stdout

    def fail(self, *args, code=1):
        r = self.h.mem(*args)
        self.assertEqual(r.returncode, code, f"{args}: {r.stdout}")
        return r.stderr

    def test_log_requires_carry_over_declaration(self):
        self.assertIn("--done", self.fail("log", "did a thing"))
        out = self.ok("log", "did a thing", "--done")
        self.assertRegex(out, r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} · agent · ")

    def test_log_line_budget(self):
        self.assertIn("budget", self.fail("log", "x" * 201, "--done"))

    def test_log_handoff_must_exist(self):
        self.assertIn("no handoff", self.fail("log", "half way", "--handoff", "nope"))

    def test_open_handoffs_are_derived_from_status(self):
        out = self.ok("handoff", "open", "Migrate config loader")
        path = self.h.vault / out.splitlines()[0]
        text = path.read_text(encoding="utf-8")
        for h in ("Where it stopped", "Concrete next step", "Why it is this way",
                  "Tried, did not work", "How I know it is done"):
            self.assertIn(f"## {h}", text)
        self.assertIn("migrate-config-loader", self.ok("handoff", "list"))
        path.write_text(text.replace("status: open", "status: paused"), encoding="utf-8")
        self.assertNotIn("migrate-config-loader", self.ok("handoff", "list"))
        path.write_text(text, encoding="utf-8")
        self.ok("handoff", "close", "migrate-config-loader")
        self.assertNotIn("migrate-config-loader", self.ok("handoff", "list"))
        self.assertTrue((self.h.vault / "archive" / "handoffs" / "migrate-config-loader.md").exists())

    def test_promotion_gate(self):
        self.ok("infer", "claim", "Cache misses on cold start", "--scope", "project")
        slug = "cache-misses-on-cold-start"
        self.assertIn("verification", self.fail("promote", slug, "--to", "topics/Caching#Cold"))
        self.assertIn("20 characters", self.fail("verify", slug, "--evidence", "looked again"))
        self.ok("verify", slug, "--evidence", "re-ran bench.py cold 3x: 3/3 misses on first call")
        self.assertIn("does not exist", self.fail("promote", slug, "--to", "topics/Caching#Cold"))
        self.ok("note", "new", "topics", "Caching", "--trigger", "cache misses / warmup")
        self.assertIn("no heading", self.fail("promote", slug, "--to", "topics/Caching#Cold start"))
        note = self.h.vault / "topics" / "Caching.md"
        note.write_text(note.read_text(encoding="utf-8") + "\n## Cold start\n\nFirst call misses.\n",
                        encoding="utf-8")
        self.ok("promote", slug, "--to", "topics/Caching#Cold start")
        rec = (self.h.vault / "inferences" / f"{slug}.md").read_text(encoding="utf-8")
        self.assertIn("status: promoted", rec)
        self.assertIn("promoted_to: topics/Caching.md#Cold start", rec)

    def test_person_scope_needs_the_user(self):
        self.ok("infer", "claim", "Prefers short answers", "--scope", "person")
        slug = "prefers-short-answers"
        self.ok("verify", slug, "--evidence", "user said so directly in this session's first prompt")
        self.assertIn("only the user", self.fail("promote", slug, "--to", "profile"))
        self.ok("promote", slug, "--to", "profile", "--user-confirmed")

    def test_claim_needs_scope(self):
        self.assertIn("--scope", self.fail("infer", "claim", "Something about builds"))

    def test_refuted_record_is_kept(self):
        self.ok("infer", "claim", "Flaky test is a race", "--scope", "project")
        self.ok("refute", "flaky-test-is-a-race", "--reason", "fails single-threaded too")
        rec = self.h.vault / "inferences" / "flaky-test-is-a-race.md"
        self.assertTrue(rec.exists())
        self.assertIn("status: refuted", rec.read_text(encoding="utf-8"))
        self.assertIn("refuted", self.ok("infer", "list", "--status", "refuted"))

    def test_duplicate_note_name_is_refused(self):
        self.ok("note", "new", "topics", "Release_Process")
        err = self.fail("note", "new", "topics", "Process_Releases", code=3)
        self.assertIn("Release_Process", err)
        self.ok("note", "new", "topics", "Process_Releases", "--force")

    def test_note_frontmatter_is_generated(self):
        self.ok("note", "new", "projects", "Atlas", "--trigger", "atlas service / map tiles")
        text = (self.h.vault / "projects" / "Atlas.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"created: \d{4}-\d{2}-\d{2} \d{2}:\d{2}")
        idx = (self.h.vault / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("- [[projects/Atlas]] — atlas service / map tiles", idx)

    def test_system_folders_are_not_note_folders(self):
        self.assertIn("not a note folder", self.fail("note", "new", "worklog", "Mine"))


if __name__ == "__main__":
    unittest.main()
