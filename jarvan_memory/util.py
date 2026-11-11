"""Shared helpers: paths, config, time, text folding, frontmatter, file I/O.

Everything here is stdlib only. Paths are resolved from the environment on
every call so tests (and a fake HOME) can redirect them.
"""
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

APP_NAME = "jarvan-memory"
# Set on every child process we spawn; every entry point exits early when it
# sees it, so a `claude -p` child can never re-enter our hooks.
CHILD_ENV = "JARVAN_MEMORY_CHILD"


# ----------------------------------------------------------------- paths

def home():
    return Path(os.path.expanduser("~"))


def claude_dir():
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else home() / ".claude"


def app_dir():
    # An installed runtime lives at <app>/runtime/jarvan_memory/util.py. Trust
    # that location over the environment: Claude Code may be started without
    # the CLAUDE_CONFIG_DIR/HOME the installer saw, and the hooks would then
    # report "not installed" for a perfectly good install.
    here = Path(__file__).resolve()
    if here.parents[1].name == "runtime" and (here.parents[2] / "config.json").is_file():
        return here.parents[2]
    return claude_dir() / APP_NAME


def state_dir():
    d = app_dir() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path():
    return app_dir() / "config.json"


def fwd(p):
    """Absolute path with forward slashes: valid in Git Bash, cmd and POSIX."""
    return str(Path(p).resolve()).replace("\\", "/")


# ----------------------------------------------------------------- config

class NotInstalled(Exception):
    pass


def load_config(required=True):
    p = config_path()
    if not p.exists():
        if required:
            raise NotInstalled(f"{APP_NAME} is not installed (no {p}).")
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_config(cfg):
    write_text(config_path(), json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def vault_dir(cfg=None):
    cfg = cfg if cfg is not None else load_config()
    return Path(cfg["vault"])


# ----------------------------------------------------------------- time
# The model has no clock and will happily invent a plausible time. Every
# timestamp in the vault is produced here, never typed by the agent.

def now():
    return datetime.now()


def stamp(dt=None):
    return (dt or now()).strftime("%Y-%m-%d %H:%M")


def today(dt=None):
    return (dt or now()).strftime("%Y-%m-%d")


def month(dt=None):
    return (dt or now()).strftime("%Y-%m")


# ----------------------------------------------------------------- text

# Letters NFKD cannot decompose; folded by hand so search works across
# languages (dotless i, sharp s, slashed o, ...).
_EXTRA_FOLD = str.maketrans({"ı": "i", "İ": "i", "ß": "ss", "ø": "o", "Ø": "o",
                             "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "æ": "ae",
                             "Æ": "ae", "œ": "oe", "Œ": "oe", "þ": "th"})


def fold(text):
    """Lowercase and strip diacritics: 'Çalışma Ağı' -> 'calisma agi'."""
    text = text.translate(_EXTRA_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def slugify(text, maxlen=60):
    s = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    return (s[:maxlen].rstrip("-")) or "note"


WORD_RE = re.compile(r"[a-z0-9]+")


def words(text):
    return WORD_RE.findall(fold(text))


# ----------------------------------------------------------------- files

def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


def write_text(path, text):
    """Atomic write: a crash never leaves a half-written note."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def append_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(text)


class FileLock:
    """Exclusive lock file (O_EXCL). A lock older than `stale` seconds is
    taken over: a crashed holder must not block writers forever."""

    def __init__(self, path, timeout=10.0, stale=120.0):
        self.path, self.timeout, self.stale = Path(path), timeout, stale

    def acquire(self, wait=True):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return True
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if not wait or time.time() > deadline:
                    return False
                time.sleep(0.05)

    def release(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(f"could not lock {self.path}")
        return self

    def __exit__(self, *a):
        self.release()


# ----------------------------------------------------------------- frontmatter

FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)


def parse_frontmatter(text):
    """Minimal flat YAML: `key: value` lines. Returns (dict, body)."""
    m = FM_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            meta[k.strip()] = v
    return meta, text[m.end():]


def _fm_value(v):
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fm_value(x) for x in v) + "]"
    v = str(v)
    # Quote only what plain YAML would misread; "2026-01-05 10:00" stays bare.
    if v == "" or re.search(r": |:$| #|^\s|\s$|^[-?!&*|>'\"%@`{\[#,]", v):
        return json.dumps(v, ensure_ascii=False)
    return v


def render_frontmatter(meta):
    lines = ["---"] + [f"{k}: {_fm_value(v)}" for k, v in meta.items()] + ["---", ""]
    return "\n".join(lines)


def update_frontmatter(path, **changes):
    text = read_text(path)
    meta, body = parse_frontmatter(text)
    meta.update({k: v for k, v in changes.items() if v is not None})
    write_text(path, render_frontmatter(meta) + body)
    return meta


# ----------------------------------------------------------------- stdio
# Windows consoles and pipes default to a legacy code page; hook payloads and
# notes are UTF-8. Always go through bytes.

def read_stdin_json():
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return {}


def out(text=""):
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.flush()


def err(text=""):
    sys.stderr.buffer.write((text + "\n").encode("utf-8"))
    sys.stderr.flush()
