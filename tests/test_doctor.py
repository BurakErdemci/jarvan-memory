"""Doctor promises: a clean install reports N/N; a vanished interpreter is
detected by doctor and announced at session start; repair-python fixes it;
the session-start block reports its own size instead of cutting."""
import json
import re
import subprocess
import sys
import unittest

from helpers import BASH, FakeHome, ctx


@unittest.skipUnless(BASH, "bash not found")
class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.h = FakeHome()
        self.h.install("--name", "Ada", "--modules", "none", "--no-doctor")

    def tearDown(self):
        self.h.cleanup()

    def doctor(self):
        r = self.h.mem("doctor", "--json")
        return r.returncode, json.loads(r.stdout)

    def test_clean_install_passes_every_check(self):
        rc, rep = self.doctor()
        failed = [r for r in rep["rows"] if r["kind"] == "check" and not r["ok"]]
        self.assertEqual(failed, [])
        self.assertEqual(rc, 0)
        self.assertEqual(rep["passed"], rep["total"])
        self.assertGreaterEqual(rep["total"], 12)

    def test_broken_interpreter_is_detected_and_announced(self):
        cfg_path = self.h.app / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        gone = str(self.h.root / "no-python" / "python.exe").replace("\\", "/")
        cfg["python"] = gone
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        hook = self.h.app / "hook.sh"
        hook.write_text(re.sub(r'^PY=".*"$', f'PY="{gone}"', hook.read_text(encoding="utf-8"),
                               flags=re.M), encoding="utf-8")
        # Doctor itself runs on any interpreter; call it directly.
        r = subprocess.run([sys.executable, str(self.h.app / "runtime" / "run.py"), "cli",
                            "doctor", "--json"], env=self.h.env, capture_output=True,
                           text=True, encoding="utf-8")
        rep = json.loads(r.stdout)
        bad = {x["name"] for x in rep["rows"] if x["kind"] == "check" and not x["ok"]}
        self.assertIn("python interpreter", bad)
        self.assertNotEqual(r.returncode, 0)
        out = ctx(self.h.hook("session-start", {"source": "startup"}))
        self.assertIn("no longer exists", out)
        self.assertIn("repair-python", out)
        r = subprocess.run([sys.executable, str(self.h.app / "runtime" / "run.py"), "cli",
                            "repair-python"], env=self.h.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rc, rep = self.doctor()
        self.assertEqual(rc, 0, [x for x in rep["rows"] if not x["ok"]])

    def test_oversized_session_block_warns_instead_of_cutting(self):
        idx = self.h.vault / "INDEX.md"
        extra = "".join(f"- [[topics/N{i}]] — READ FIRST {'x' * 3000}\n" for i in range(4))
        idx.write_text(idx.read_text(encoding="utf-8") + extra, encoding="utf-8")
        out = ctx(self.h.hook("session-start", {"source": "startup"}))
        self.assertIn("over the 8000 budget", out)
        self.assertEqual(out.count("x" * 3000), 3, "lines within the cap are shown whole")
        self.assertIn("+1 more READ FIRST line(s)", out, "lines over the cap are announced")


if __name__ == "__main__":
    unittest.main()
