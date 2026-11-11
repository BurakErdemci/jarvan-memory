"""`mem doctor`: check the installation end to end and print N/N.

Every check exercises the real entry point where it can: hooks are probed by
running the exact command string registered in settings.json through bash,
with a probe payload, and the reply is parsed. A check that only looked at
files would stay green while the hook itself was dead.
"""
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from . import util, vault as V

PROBE = "jm-doctor-probe"
HOOK_ERROR_DAYS = 7


class Report:
    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=""):
        self.rows.append(("check", name, bool(ok), detail))

    def warn(self, name, detail):
        self.rows.append(("warn", name, False, detail))

    def info(self, name, detail):
        self.rows.append(("info", name, True, detail))

    @property
    def checks(self):
        return [r for r in self.rows if r[0] == "check"]


def find_bash():
    """Claude Code on Windows runs hooks with Git Bash, not WSL's bash.exe."""
    env = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if env and Path(env).is_file():
        return env
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            root = Path(git).resolve().parent.parent
            for cand in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
                if cand.is_file():
                    return str(cand)
        b = shutil.which("bash")
        if b and "system32" not in b.lower():
            return b
        return None
    return shutil.which("bash")


def run_command(bash, command, payload, timeout=30):
    r = subprocess.run([bash, "-c", command], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def registered(settings):
    """{hook-name: command} for our entries in settings.json."""
    out = {}
    for ev, groups in (settings.get("hooks") or {}).items():
        for g in groups if isinstance(groups, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                cmd = str(h.get("command", ""))
                if "jarvan-memory/hook.sh" in cmd:
                    out[cmd.rsplit(" ", 1)[-1]] = (ev, g.get("matcher"), cmd)
    return out


def run_checks():
    from . import installer, search
    rep = Report()
    try:
        cfg = util.load_config()
    except util.NotInstalled as e:
        rep.check("config", False, str(e))
        return rep, {}
    rep.check("config", True, util.fwd(util.config_path()))

    py = cfg.get("python", "")
    real = installer.probe_python(py) if py else None
    rep.check("python interpreter", bool(real),
              real or f"{py!r} does not run; run `mem repair-python` (see INSTALL.md)")

    app = util.app_dir()
    files = [app / "hook.sh", app / "bin" / "mem", app / "bin" / "mem.cmd",
             app / "runtime" / "run.py", app / "runtime" / "jarvan_memory" / "hooks.py"]
    missing = [util.fwd(f) for f in files if not f.exists()]
    left = [util.fwd(f) for f in files[:3] if f.exists()
            and installer.PLACEHOLDER_RE.search(util.read_text(f))]
    rep.check("runtime files", not missing and not left,
              "ok" if not (missing or left) else f"missing {missing} placeholders {left}")

    try:
        settings = installer.read_settings() or {}
        reg = registered(settings)
    except SystemExit as e:
        settings, reg = {}, {}
        rep.check("hooks registered", False, str(e))
    else:
        want = {name: (ev, m) for ev, m, name, _ in installer.HOOKS}
        bad = [n for n, (ev, m) in want.items() if n not in reg or reg[n][:2] != (ev, m)]
        rep.check("hooks registered", not bad,
                  f"{len(want)} events in settings.json" if not bad else f"missing/wrong: {bad}")

    bash = find_bash()
    if not bash:
        rep.check("hooks fire", False, "no bash found (Windows: install Git for Windows)")
    elif reg:
        _probe_hooks(rep, bash, reg, cfg)

    vroot = Path(cfg.get("vault", ""))
    rep.check("vault writable", _writable(vroot), util.fwd(vroot))
    gaps = [d for d in V.SKELETON_DIRS + V.SKELETON_FILES if not (vroot / d).exists()]
    rep.check("vault skeleton", not gaps, "complete" if not gaps else f"missing {gaps}")

    ph = []
    for f in [vroot / V.CONTRACT, vroot / V.INDEX, vroot / V.PROFILE,
              *sorted((vroot / V.TEMPLATES).glob("*.md")), installer.claude_md_path()]:
        if f.exists() and installer.PLACEHOLDER_RE.search(util.read_text(f)):
            ph.append(V.rel(f, vroot) if str(f).startswith(str(vroot)) else util.fwd(f))
    rep.check("no leftover placeholders", not ph, "none" if not ph else f"in {ph}")

    md = installer.claude_md_path()
    md_ok = md.exists() and installer.BLOCK_BEGIN in util.read_text(md) and \
        util.fwd(vroot / V.CONTRACT) in util.read_text(md)
    rep.check("CLAUDE.md pointer", md_ok, util.fwd(md) if md_ok else "block missing or stale; re-run install")

    rep.check(*_search_check(cfg))
    if not search.fts5_available():
        rep.warn("FTS5", "this SQLite has no FTS5; search uses a slower fallback scan")

    mods = set(cfg.get("modules") or [])
    if mods & {"summary", "sweep"}:
        from . import jobs
        c = jobs.find_claude(cfg)
        rep.check("claude CLI (summary/sweep)", bool(c), c or "not found on PATH")
    if "backup" in mods:
        ok = shutil.which("git") and (vroot / ".git").exists()
        rep.check("git backup", ok, "vault is a git repo" if ok else "git missing or vault not a repo")

    errs = _read_json(util.state_dir() / "job-errors.json")
    for k, v in errs.items():
        rep.warn(f"last {k} job", v)
    recent = _recent_hook_errors()
    if recent:
        rep.warn("recent hook errors", f"{len(recent)} in the last {HOOK_ERROR_DAYS} days; "
                 f"last: {recent[-1]} (log: {util.fwd(util.state_dir() / 'hook-errors.log')})")
    hb = _read_json(util.state_dir() / "heartbeat.json")
    rep.info("last real hook runs", ", ".join(f"{k} {v}" for k, v in sorted(hb.items()))
             or "none yet: hooks fire from the next Claude Code session (restart it)")
    return rep, cfg


def _probe_hooks(rep, bash, reg, cfg):
    sid = f"{PROBE}-{uuid.uuid4().hex[:8]}"
    base = {"session_id": sid, "cwd": os.getcwd(), "transcript_path": ""}
    failures = []

    def call(name, extra):
        if name not in reg:
            failures.append(f"{name}: not registered")
            return None
        try:
            rc, out, err = run_command(bash, reg[name][2], dict(base, **extra))
        except subprocess.TimeoutExpired:
            failures.append(f"{name}: timed out")
            return None
        if rc != 0:
            failures.append(f"{name}: exit {rc} {err.strip()[:120]}")
            return None
        return out.strip()

    out = call("session-start", {"hook_event_name": "SessionStart", "source": "startup"})
    try:
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""
    except (ValueError, KeyError, TypeError):
        ctx = ""
    if out is not None and "jarvan-memory" not in ctx:
        failures.append("session-start: no context injected")
    for name, extra in [("user-prompt", {"prompt": "doctor probe"}),
                        ("post-tool", {"tool_name": "Read", "tool_input": {}}),
                        ("tool-failure", {"tool_name": "Bash", "error": "probe"})]:
        call(name, extra)
    rep.check("hooks fire", not failures,
              "session-start, user-prompt, post-tool, tool-failure answered" if not failures
              else "; ".join(failures))

    out = call("stop", {"hook_event_name": "Stop", "stop_hook_active": False,
                        "jm_probe_prompts": 999})
    try:
        armed = json.loads(out or "{}").get("decision") == "block"
    except ValueError:
        armed = False
    rep.check("stop gate armed", armed, "blocks a long session with no memory write"
              if armed else f"no block decision (got {out!r:.80})")

    wl = Path(cfg["vault"]) / V.WORKLOG / "2000-01.md"
    out = call("pre-tool", {"tool_name": "Write",
                            "tool_input": {"file_path": util.fwd(wl), "content": "x"}})
    try:
        deny = json.loads(out or "{}")["hookSpecificOutput"]["permissionDecision"] == "deny"
    except (ValueError, KeyError, TypeError):
        deny = False
    rep.check("worklog timestamp guard", deny, "rejects hand-written worklog files"
              if deny else f"no deny (got {out!r:.80})")

    mem = cfg.get("mem_cmd", "")
    try:
        rc, out2, err = run_command(bash, f"{mem} --version", {})
        ok = rc == 0 and "jarvan-memory" in out2
    except (OSError, subprocess.SubprocessError) as e:
        ok, err = False, str(e)
    rep.check("mem command runs", ok, mem if ok else (err or out2)[:160])


def _writable(vroot):
    try:
        if not vroot.is_dir():
            return False
        p = vroot / f".mem-doctor-{uuid.uuid4().hex[:6]}"
        p.write_text("x", encoding="utf-8")
        p.unlink()
        return True
    except OSError:
        return False


def _search_check(cfg):
    """Index a throwaway vault with a known note and require that exact note
    back: a search that returns nothing would otherwise read as 'no match'."""
    from . import search
    token = "zq" + uuid.uuid4().hex[:6]
    with tempfile.TemporaryDirectory(prefix="jm-doctor-") as d:
        root = Path(d)
        (root / "topics").mkdir()
        (root / "topics" / "Probe.md").write_text(
            f"# Probe\n\n## Known answer\n\nThe {token} calibration value lives here.\n",
            encoding="utf-8")
        (root / "topics" / "Other.md").write_text("# Other\n\nUnrelated text.\n", encoding="utf-8")
        try:
            res = search.search(f"where is the {token} calibration", root=root, cfg=cfg)
            ok = bool(res) and res[0]["path"] == "topics/Probe.md" and res[0]["lines"][0][0] == 5
        except Exception as e:
            return ("search works", False, f"{type(e).__name__}: {e}")
        finally:
            for s in ("", "-wal", "-shm"):
                Path(str(search.db_path(root)) + s).unlink(missing_ok=True)
    try:
        con = search.update_index(cfg=cfg)
        n = con.execute("SELECT count(*) FROM sections").fetchone()[0]
        con.close()
    except Exception as e:
        return ("search works", False, f"vault index: {type(e).__name__}: {e}")
    return ("search works", ok, f"known-answer probe ok; vault index has {n} sections"
            if ok else "known-answer probe did not return the probe note at line 5")


def _recent_hook_errors():
    """Lines of state/hook-errors.log from the last HOOK_ERROR_DAYS days.
    Hooks swallow their own failures so a bug never breaks a session; this is
    where they surface."""
    p = util.state_dir() / "hook-errors.log"
    try:
        lines = util.read_text(p).splitlines()
    except OSError:
        return []
    since = util.stamp(util.now() - timedelta(days=HOOK_ERROR_DAYS))
    return [l for l in lines if l.strip() and l[:16] >= since]


def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(json_out=False):
    rep, _ = run_checks()
    checks = rep.checks
    passed = sum(1 for c in checks if c[2])
    if json_out:
        util.out(json.dumps({"passed": passed, "total": len(checks),
                             "rows": [dict(zip(("kind", "name", "ok", "detail"), r))
                                      for r in rep.rows]}, ensure_ascii=False, indent=1))
    else:
        util.out("jarvan-memory doctor")
        for kind, name, ok, detail in rep.rows:
            mark = {"check": "PASS" if ok else "FAIL", "warn": "WARN", "info": "INFO"}[kind]
            util.out(f"  [{mark}] {name}: {detail}")
        util.out(f"{passed}/{len(checks)} checks passing")
    return 0 if passed == len(checks) else 1
