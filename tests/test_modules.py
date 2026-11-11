"""Optional module promises. The paid model is the boundary, so `claude` is
replaced by a fake that records its arguments and environment and replays a
canned reply; everything else (detached spawn, locking, schema check, git)
is real."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from helpers import BASH, FakeHome, ctx

VALID = "\n".join(f"## {h}\n- something" for h in
                  ["Context", "Decisions", "Tried and failed", "Learned", "Open questions",
                   "Next steps"])

FAKE_CLAUDE_PY = r'''
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
prompt = sys.stdin.read()
with open(os.path.join(d, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "child": os.environ.get("JARVAN_MEMORY_CHILD"),
                        "prompt": prompt[:20000]}) + "\n")
with open(os.path.join(d, "reply.txt"), encoding="utf-8") as f:
    sys.stdout.write(f.read())
'''


def transcript(path, chars):
    with open(path, "w", encoding="utf-8") as f:
        n = 0
        i = 0
        while n < chars:
            text = f"turn {i}: we changed the parser and measured the fixture timings " * 3
            f.write(json.dumps({"type": "user" if i % 2 == 0 else "assistant",
                                "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
            n += len(text)
            i += 1


@unittest.skipUnless(BASH, "bash not found")
class ModulesTest(unittest.TestCase):
    def setUp(self):
        self.h = FakeHome()
        self.fake = self.h.root / "fakeclaude"
        self.fake.mkdir()
        (self.fake / "fake.py").write_text(FAKE_CLAUDE_PY, encoding="utf-8")
        if os.name == "nt":
            exe = self.fake / "claude.cmd"
            exe.write_text(f'@"{sys.executable}" "{self.fake / "fake.py"}" %*\r\n', encoding="utf-8")
        else:
            exe = self.fake / "claude"
            exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{self.fake / "fake.py"}" "$@"\n',
                           encoding="utf-8")
            exe.chmod(0o755)
        self.reply(VALID)
        self.h.env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})
        self.h.install("--modules", "summary,backup,sweep", "--no-doctor")
        cfgp = self.h.app / "config.json"
        cfg = json.loads(cfgp.read_text(encoding="utf-8"))
        cfg["claude_path"] = str(exe)
        cfgp.write_text(json.dumps(cfg), encoding="utf-8")

    def tearDown(self):
        self.h.cleanup()

    def reply(self, text):
        (self.fake / "reply.txt").write_text(text, encoding="utf-8")

    def calls(self):
        p = self.fake / "calls.jsonl"
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def job(self, *args):
        return subprocess.run([sys.executable, str(self.h.app / "runtime" / "run.py"), "job", *args],
                              env=self.h.env, capture_output=True, text=True, timeout=120)

    def end_job(self, chars, sid="m1"):
        tp = self.h.root / f"{sid}.jsonl"
        transcript(tp, chars)
        pf = self.h.root / f"{sid}-payload.json"
        pf.write_text(json.dumps({"payload": {"session_id": sid, "transcript_path": str(tp)},
                                  "project": "demo"}), encoding="utf-8")
        r = self.job("session-end", str(pf))
        self.assertEqual(r.returncode, 0, r.stderr)

    def daily(self):
        return "".join(p.read_text(encoding="utf-8") for p in (self.h.vault / "daily").glob("*.md"))

    def test_summary_child_never_loads_user_hooks(self):
        self.end_job(5000)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        i = argv.index("--setting-sources")
        self.assertEqual(argv[i + 1], "", "the child must get an empty setting source list")
        self.assertEqual(calls[0]["child"], "1")
        self.assertIn("UNTRUSTED TRANSCRIPT DATA", calls[0]["prompt"])
        self.assertIn("### Decisions", self.daily())

    def test_tiny_session_makes_no_model_call(self):
        self.end_job(500)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.daily(), "")

    def test_schema_invalid_summary_writes_nothing_and_is_reported(self):
        self.reply("Sure! Here is a summary of the session: it went well.")
        self.end_job(5000)
        self.assertEqual(self.daily(), "")
        out = ctx(self.h.hook("session-start", {"source": "startup"}))
        self.assertIn("summary", out)
        self.assertIn("schema", out)

    def test_backup_commits_vault_and_pushes_only_with_remote(self):
        self.reply("NOTHING_TO_KEEP")
        self.h.mem("log", "first entry", "--done")
        self.end_job(100)
        log = subprocess.run(["git", "-C", str(self.h.vault), "log", "--oneline"],
                             capture_output=True, text=True)
        self.assertIn("mem: session end", log.stdout)
        bare = self.h.root / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        subprocess.run(["git", "-C", str(self.h.vault), "remote", "add", "origin", str(bare)], check=True)
        branch = subprocess.run(["git", "-C", str(self.h.vault), "branch", "--show-current"],
                                capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", str(self.h.vault), "push", "-q", "-u", "origin", branch],
                       check=True, env=self.h.env)
        self.h.mem("log", "second entry", "--done")
        self.end_job(100, sid="m2")
        remote_log = subprocess.run(["git", "-C", str(bare), "log", "--oneline", branch],
                                    capture_output=True, text=True).stdout
        self.assertEqual(remote_log.count("mem: session end"), 2)

    def test_session_end_hook_runs_summary_detached(self):
        tp = self.h.root / "live.jsonl"
        transcript(tp, 5000)
        for _ in range(3):
            self.h.hook("user-prompt", {"session_id": "live1", "prompt": "ok"})
        t0 = time.time()
        self.h.hook("session-end", {"session_id": "live1", "transcript_path": str(tp)})
        self.assertLess(time.time() - t0, 10, "the hook must not wait for the model")
        deadline = time.time() + 60
        while time.time() < deadline and "### Decisions" not in self.daily():
            time.sleep(0.5)
        self.assertIn("### Decisions", self.daily())

    def test_sweep_proposes_only_quote_backed_refutations(self):
        self.h.mem("infer", "claim", "Fixture timings are stable", "--scope", "project",
                   "--text", "fixture timings stay under one second")
        self.h.mem("log", "measured fixture timings: parser fixtures take 4 seconds now", "--done")
        quote = "parser fixtures take 4 seconds now"
        good = [{"record": "fixture-timings-are-stable", "verdict": "refute", "quote": quote,
                 "source": None, "reason": "timings grew"}]
        # Learn the evidence id the sweep sends, then answer with it.
        self.reply("[]")
        self.assertEqual(self.job("sweep").returncode, 0)
        prompt = self.calls()[-1]["prompt"]
        src = next(l.split("id=", 1)[1] for l in prompt.splitlines() if l.startswith("EVIDENCE id="))
        good[0]["source"] = src
        bad = [dict(good[0], quote="parser fixtures are always very slow on every machine")]
        self.reply(json.dumps(bad))
        self.job("sweep")
        self.assertEqual(list((self.h.vault / "sweeps").glob("*.md")), [],
                         "a quote not found in the evidence must be dropped")
        self.reply(json.dumps(good))
        self.job("sweep")
        reports = list((self.h.vault / "sweeps").glob("*.md"))
        self.assertEqual(len(reports), 1)
        self.assertIn("proposed: refute", reports[0].read_text(encoding="utf-8"))
        rec = (self.h.vault / "inferences" / "fixture-timings-are-stable.md").read_text(encoding="utf-8")
        self.assertIn("status: unverified", rec, "the sweep never changes a record")


if __name__ == "__main__":
    unittest.main()
