"""Test harness: a throwaway HOME with its own Claude config dir.

Tests drive the real entry points (install.py, the generated hook shim run
through bash, the generated `mem` launcher) and look at what they leave on
disk. Nothing here touches the real home directory.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from jarvan_memory.doctor import find_bash  # noqa: E402

BASH = find_bash()


def rmtree(path):
    """Delete a test tree for real. On Windows git object files are
    read-only and a just-exited detached job may still hold a log file
    open, so clear the flag and retry briefly."""
    import stat
    import time

    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    for _ in range(20):
        shutil.rmtree(path, onerror=onerror)
        if not Path(path).exists():
            return
        time.sleep(0.25)
    raise AssertionError(f"test left {path} behind")


def _tmp_root():
    # The temp dir must not sit inside a git repository: tests that call
    # `git rev-parse` would find the parent repo and go falsely red.
    base = Path(tempfile.gettempdir())
    d = Path(tempfile.mkdtemp(prefix="jm-test-", dir=base))
    return d


class FakeHome:
    def __init__(self):
        self.root = _tmp_root()
        self.home = self.root / "home"
        self.home.mkdir()
        self.claude = self.home / ".claude"
        self.vault = self.home / "vault"
        self.env = dict(os.environ)
        for k in ("JARVAN_MEMORY_CHILD",):
            self.env.pop(k, None)
        self.env.update({"HOME": str(self.home), "USERPROFILE": str(self.home),
                         "CLAUDE_CONFIG_DIR": str(self.claude),
                         "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        self.work = self.root / "work"
        self.work.mkdir()

    def cleanup(self):
        rmtree(self.root)

    @property
    def app(self):
        return self.claude / "jarvan-memory"

    @property
    def settings(self):
        return self.claude / "settings.json"

    def install(self, *args, check=True):
        args = list(args)
        if "--vault" not in args:
            args += ["--vault", str(self.vault)]
        r = subprocess.run([sys.executable, str(REPO / "install.py"), *args], env=self.env,
                           capture_output=True, text=True, encoding="utf-8", cwd=str(self.work))
        if check and r.returncode != 0:
            raise AssertionError(f"install failed rc={r.returncode}\n{r.stdout}\n{r.stderr}")
        return r

    def mem(self, *args, cwd=None):
        """Run the generated launcher through bash, as the agent would."""
        cmd = '"' + str(self.app / "bin" / "mem").replace("\\", "/") + '"'
        line = " ".join([cmd] + [_q(a) for a in args])
        return subprocess.run([BASH, "-c", line], env=self.env, capture_output=True,
                              text=True, encoding="utf-8", cwd=str(cwd or self.work))

    def hook_command(self, name):
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        for groups in data["hooks"].values():
            for g in groups:
                for h in g["hooks"]:
                    if "jarvan-memory/hook.sh" in h["command"] and h["command"].endswith(" " + name):
                        return h["command"]
        raise AssertionError(f"hook {name} not registered")

    def hook(self, name, payload):
        """Run the exact registered command string, as Claude Code does."""
        payload = dict({"session_id": "s1", "cwd": str(self.work)}, **payload)
        r = subprocess.run([BASH, "-c", self.hook_command(name)], env=self.env,
                           input=json.dumps(payload).encode("utf-8"), capture_output=True)
        out = r.stdout.decode("utf-8").strip()
        assert r.returncode == 0, f"hook {name} rc={r.returncode} {r.stderr!r}"
        return json.loads(out) if out else None


def _q(a):
    return "'" + str(a).replace("'", "'\\''") + "'"


class HomeTest(unittest.TestCase):
    """A fresh fake home, installed once per test class."""
    install_args = ("--name", "Ada", "--about", "Builds data tools.", "--modules", "none",
                    "--no-doctor")

    @classmethod
    def setUpClass(cls):
        if not BASH:
            raise unittest.SkipTest("bash not found")
        cls.h = FakeHome()
        cls.h.install(*cls.install_args)

    @classmethod
    def tearDownClass(cls):
        cls.h.cleanup()


def ctx(reply):
    return (reply or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
