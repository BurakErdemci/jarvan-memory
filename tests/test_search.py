"""Search and suggestion promises: the right note and line come back; text is
matched across diacritics; prompt suggestions and failure recall stay
silent unless the match is strong; the no-FTS5 fallback finds the same note."""
import os
import shutil
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from helpers import HomeTest, ctx

from jarvan_memory import search

NOTES = {
    "topics/Deploy.md": "# Deploy\n\n## Rollback\n\nTo roll back a release run `make rollback` "
                        "with the previous tag; the database migration is not reverted.\n",
    "topics/Testing.md": "# Testing\n\n## Fixtures\n\nFixtures live in tests/data.\n",
    "topics/Calisma.md": "# Çalışma düzeni\n\nSabahları derin iş, öğleden sonra toplantı.\n",
    "topics/Notlar.md": "# Notlar\n\nKısa not yazma kuralları burada.\n",
    "topics/Sqlite.md": "# SQLite\n\n## Locked database\n\nsqlite3.OperationalError database is "
                        "locked happens when the indexer and the hook write together; the "
                        "indexer now uses BEGIN IMMEDIATE with a short busy timeout.\n",
}


class SearchUnitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jm-search-"))
        self.env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude")})
        self.env.start()
        self.root = self.tmp / "vault"
        for rel, text in NOTES.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        self.cfg = {"vault": str(self.root)}

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_note_line_range_and_line(self):
        res = search.search("how do I roll back a release", root=self.root, cfg=self.cfg)
        self.assertEqual(res[0]["path"], "topics/Deploy.md")
        self.assertEqual((res[0]["start"], res[0]["end"]), (3, 5))
        self.assertEqual(res[0]["lines"][0][0], 5)
        self.assertIn("make rollback", res[0]["lines"][0][1])

    def test_diacritics_fold_both_ways(self):
        res = search.search("calisma duzeni", root=self.root, cfg=self.cfg)
        self.assertEqual(res[0]["path"], "topics/Calisma.md")
        res = search.search("öğleden toplantı", root=self.root, cfg=self.cfg)
        self.assertEqual(res[0]["path"], "topics/Calisma.md")

    def test_index_updates_when_a_note_changes(self):
        token = "zz" + uuid.uuid4().hex[:6]
        self.assertEqual(search.search(token + " marker", root=self.root, cfg=self.cfg), [])
        p = self.root / "topics" / "Testing.md"
        p.write_text(p.read_text(encoding="utf-8") + f"\n## New\n\n{token} marker here.\n",
                     encoding="utf-8")
        res = search.search(token + " marker", root=self.root, cfg=self.cfg)
        self.assertEqual(res[0]["path"], "topics/Testing.md")

    def test_fallback_without_fts5_finds_the_same_note(self):
        with mock.patch.object(search, "fts5_available", return_value=False):
            res = search.search("roll back release migration", root=self.root, cfg=self.cfg)
        self.assertEqual(res[0]["path"], "topics/Deploy.md")

    def test_line_numbers_count_only_newlines(self):
        # U+2028 and form feed are not line breaks for an editor or the Read tool.
        p = self.root / "topics" / "Pasted.md"
        p.write_bytes("# Pasted\n\nfirst\u2028second\x0cthird\n\n## Zebra migration plan\n\n"
                      "migrate the zebra database nightly\n".encode("utf-8"))
        res = search.search("zebra migration plan database", root=self.root, cfg=self.cfg)
        real = next(i for i, l in enumerate(p.read_bytes().decode("utf-8").split("\n"), 1)
                    if l.startswith("## Zebra"))
        self.assertEqual(res[0]["path"], "topics/Pasted.md")
        self.assertEqual(res[0]["start"], real)
        self.assertEqual(res[0]["lines"][0][0], real + 2)

    def test_refuted_and_promoted_records_weigh_less(self):
        now = time.time()
        live = search._weight("", "Heading", now, "topics/a.md")
        self.assertLessEqual(search._weight("refuted", "Heading", now, "inferences/a.md"),
                             0.31 * live)
        self.assertLessEqual(search._weight("promoted", "Heading", now, "inferences/a.md"),
                             0.51 * live)

    def test_turkish_stemmer_plugin(self):
        cfg = dict(self.cfg, stemmer="tr")
        res = search.search("notlarımızda kural", root=self.root, cfg=cfg)
        self.assertEqual(res[0]["path"], "topics/Notlar.md")


class SuggestTest(HomeTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for rel, text in NOTES.items():
            p = cls.h.vault / rel
            p.write_text(text, encoding="utf-8")

    def prompt(self, text):
        return ctx(self.h.hook("user-prompt", {"session_id": "p" + uuid.uuid4().hex[:6],
                                               "prompt": text}))

    def test_strong_match_is_suggested_with_line_range(self):
        out = self.prompt("roll back the release, is the migration reverted?")
        self.assertIn("topics/Deploy.md:3-5", out)

    def test_weak_partial_overlap_is_silent(self):
        # Three words hit the Deploy note, but most of the prompt is elsewhere.
        out = self.prompt("database migration rollback plan for kubernetes helm terraform "
                          "ansible secrets rotation")
        self.assertEqual(out, "")

    def test_two_matched_words_are_never_enough(self):
        # Both content words hit the Deploy note; the gate wants three.
        self.assertEqual(self.prompt("rollback migration"), "")

    def test_index_trigger_words_count_toward_the_gate(self):
        (self.h.vault / "topics" / "Gizmo.md").write_text(
            "# Gizmo\n\n## Notes\n\nunrelated words only here\n", encoding="utf-8")
        idx = self.h.vault / "INDEX.md"
        idx.write_text(idx.read_text(encoding="utf-8") +
                       "- [[topics/Gizmo]] \u2014 how do I rebuild the gizmo pipeline safely\n",
                       encoding="utf-8")
        self.assertIn("topics/Gizmo.md", self.prompt("how do I rebuild the gizmo pipeline safely"))

    def test_a_non_ascii_prompt_reaches_the_suggestion(self):
        out = self.prompt("sabahlar\u0131 derin i\u015f \u00f6\u011fleden sonra toplant\u0131")
        self.assertIn("topics/Calisma.md", out)

    def test_refuted_records_are_never_suggested(self):
        rec = self.h.vault / "inferences" / "r1.md"
        body = ("# r1\n\n## Claim\n\nroll back staging release by deleting the cache "
                "directory entirely\n")
        ask = "how do I roll back the staging release by deleting the cache directory"
        rec.write_text("---\ntitle: r1\nstatus: unverified\n---\n" + body, encoding="utf-8")
        self.assertIn("inferences/r1.md", self.prompt(ask), "control: an unverified one is")
        rec.write_text("---\ntitle: r1\nstatus: refuted\n---\n" + body, encoding="utf-8")
        self.assertNotIn("inferences/r1.md", self.prompt(ask))

    def test_unrelated_prompt_is_silent(self):
        self.assertEqual(self.prompt("write a haiku about autumn leaves"), "")
        self.assertEqual(self.prompt("thanks!"), "")

    def test_recall_on_failure_at_most_two_and_only_when_confident(self):
        err = ("Traceback (most recent call last):\n  File \"index.py\", line 3\n"
               "sqlite3.OperationalError: database is locked")
        out = ctx(self.h.hook("tool-failure", {"session_id": "r1", "tool_name": "Bash",
                                               "error": err}))
        self.assertIn("topics/Sqlite.md", out)
        self.assertLessEqual(out.count("\n- "), 2)
        again = ctx(self.h.hook("tool-failure", {"session_id": "r1", "tool_name": "Bash",
                                                 "error": err}))
        self.assertEqual(again, "", "same note is not recalled twice in a session")
        generic = ctx(self.h.hook("tool-failure", {"session_id": "r2", "tool_name": "Bash",
                                                   "error": "Exit code 1"}))
        self.assertEqual(generic, "")


if __name__ == "__main__":
    unittest.main()
