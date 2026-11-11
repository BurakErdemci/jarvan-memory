"""Vault operations: the single writer for worklog, handoffs, inferences and
new notes. Every write path that carries a date goes through util.stamp().

Folder names, frontmatter keys and status tokens are fixed English
identifiers; the prose inside notes may be in any language.
"""
import os
import re
import subprocess
from pathlib import Path

from . import util

# Fixed layout. Changing a name here is a breaking change for every vault.
WORKLOG = "worklog"
HANDOFFS = "handoffs"
INFERENCES = "inferences"
TOPICS = "topics"
PROJECTS = "projects"
DAILY = "daily"
ARCHIVE = "archive"
SWEEPS = "sweeps"
TEMPLATES = "templates"
CONTRACT = "AGENT.md"
INDEX = "INDEX.md"
PROFILE = "profile.md"

SYSTEM_DIRS = {WORKLOG, HANDOFFS, INFERENCES, DAILY, ARCHIVE, SWEEPS, TEMPLATES}
SKELETON_DIRS = [TOPICS, PROJECTS, WORKLOG, HANDOFFS, INFERENCES, DAILY,
                 ARCHIVE, SWEEPS, TEMPLATES]
SKELETON_FILES = [CONTRACT, INDEX, PROFILE]

# Worklog lines are pointers, not notes: session start shows them whole, so
# a long line either bloats every session or gets cut. Detail goes to a handoff.
LINE_BUDGET = 200
# A verification older than this is not "fresh" for promotion.
VERIFY_FRESH_DAYS = 14
# Priority marker inside an INDEX line; session start shows these lines.
PRIORITY_TOKEN = "READ FIRST"
MAX_PRIORITY_LINES = 4

HANDOFF_HEADINGS = [
    "Where it stopped",
    "Concrete next step",
    "Why it is this way",
    "Tried, did not work",
    "How I know it is done",
]

TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}")
WORKLOG_LINE_RE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (agent|session) · ([^·]+?) · (.*)$")


class MemError(Exception):
    """User-facing error: printed without a traceback, exit code 1."""
    code = 1


class DuplicateError(MemError):
    code = 3


# ----------------------------------------------------------------- helpers

def vault():
    return util.vault_dir()


def rel(path, root=None):
    root = Path(root or vault())
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def current_project(cwd=None):
    """Project label = basename of the git top level, else of the cwd."""
    cwd = cwd or os.getcwd()
    try:
        top = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5,
                             encoding="utf-8", errors="replace")
        if top.returncode == 0 and top.stdout.strip():
            return Path(top.stdout.strip()).name
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(cwd).name or "general"


def _check_no_timestamp(text, what):
    if TS_RE.search(text or ""):
        raise MemError(
            f"{what} contains a typed timestamp. Do not type dates or times: "
            "the command stamps them from the system clock (the model has no clock).")


def iter_notes(root=None, include_system=True):
    root = Path(root or vault())
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        relp = Path(dirpath).relative_to(root).parts
        if relp and not include_system and relp[0] in SYSTEM_DIRS:
            continue
        for fn in filenames:
            if fn.endswith(".md"):
                yield Path(dirpath) / fn


# ----------------------------------------------------------------- worklog

def worklog_file(dt=None):
    return vault() / WORKLOG / f"{util.month(dt)}.md"


def _ensure_worklog(path):
    if not path.exists():
        head = util.render_frontmatter({
            "title": f"Worklog {path.stem}", "created": util.stamp(),
            "type": "worklog"})
        util.write_text(path, head + f"# Worklog {path.stem}\n\n"
                        "Append-only. Written by `mem log` and the session-end hook; "
                        "never by hand.\n\n## Entries\n\n")


def append_worklog(kind, project, body):
    path = worklog_file()
    with util.FileLock(util.state_dir() / "worklog.lock"):
        _ensure_worklog(path)
        line = f"- {util.stamp()} · {kind} · {project.strip() or 'general'} · {body}\n"
        util.append_text(path, line)
    return line.rstrip("\n")


def log(text, next_step=None, handoff=None, done=False, project=None):
    """Agent worklog line. Whether work is carried over is a required, binary
    declaration: a handoff slug or --done. An optional field gets skipped."""
    text = " ".join((text or "").split())
    next_step = " ".join((next_step or "").split())
    if not text:
        raise MemError("empty worklog text")
    if bool(handoff) == bool(done):
        raise MemError(
            "say whether work is carried over: pass --handoff <slug> (open a handoff "
            "first with `mem handoff open`) or --done (nothing left open).")
    _check_no_timestamp(text + " " + next_step, "worklog text")
    body = text + (f" · next: {next_step}" if next_step else "")
    if len(body) > LINE_BUDGET:
        raise MemError(
            f"worklog line is {len(body)} chars; the budget is {LINE_BUDGET}. "
            "A worklog line is a pointer: put the detail in a handoff note or a topic "
            "note and keep the line short.")
    if handoff:
        if not find_handoff(handoff, include_closed=True):
            raise MemError(f"no handoff named '{handoff}'. Open it first: "
                           f"mem handoff open \"<title>\" --slug {handoff}")
        body += f" · handoff: [[{HANDOFFS}/{handoff}]]"
    else:
        body += " · done"
    return append_worklog("agent", project or current_project(), body)


def read_worklog(limit_months=3):
    """Parsed worklog entries, oldest first, from the newest monthly files."""
    d = vault() / WORKLOG
    if not d.is_dir():
        return []
    files = sorted(p for p in d.glob("*.md") if re.match(r"\d{4}-\d{2}$", p.stem))
    entries = []
    for p in files[-limit_months:]:
        for line in util.read_text(p).splitlines():
            m = WORKLOG_LINE_RE.match(line)
            if m:
                entries.append({"ts": m.group(1), "kind": m.group(2),
                                "project": m.group(3).strip(), "body": m.group(4)})
    return entries


# ----------------------------------------------------------------- handoffs

def find_handoff(slug, include_closed=False):
    p = vault() / HANDOFFS / f"{slug}.md"
    if p.exists():
        return p
    if include_closed:
        p = vault() / ARCHIVE / HANDOFFS / f"{slug}.md"
        if p.exists():
            return p
    return None


def handoff_open(title, slug=None, project=None):
    _check_no_timestamp(title, "title")
    slug = util.slugify(slug or title)
    if find_handoff(slug, include_closed=True):
        raise MemError(f"handoff '{slug}' already exists; pick another --slug")
    meta = {"title": title, "project": project or current_project(),
            "status": "open", "created": util.stamp(), "updated": util.stamp(),
            "source": "claude-code"}
    body = f"# {title}\n\n" + "".join(f"## {h}\n\n\n" for h in HANDOFF_HEADINGS)
    path = vault() / HANDOFFS / f"{slug}.md"
    util.write_text(path, util.render_frontmatter(meta) + body)
    return path


def handoff_close(slug):
    path = find_handoff(slug)
    if not path:
        raise MemError(f"no open handoff named '{slug}'")
    util.update_frontmatter(path, status="closed", closed=util.stamp(),
                            updated=util.stamp())
    # Closed handoffs are archived, never deleted: "tried X, it failed" keeps
    # the next session from trying X again.
    dest = vault() / ARCHIVE / HANDOFFS / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, dest)
    return dest


def open_handoffs():
    """Derived from each note's own status on every call. A stored list of
    open work drifts from what it lists, and a stale list reads as current."""
    d = vault() / HANDOFFS
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.md")):
        meta, _ = util.parse_frontmatter(util.read_text(p))
        if meta.get("status", "").strip() == "open":
            out.append({"slug": p.stem, "title": meta.get("title", p.stem),
                        "project": meta.get("project", ""),
                        "created": meta.get("created", ""), "path": p})
    return out


# ----------------------------------------------------------------- inferences

STATUSES = ("observation", "unverified", "verified", "promoted", "refuted")


def inference_path(slug):
    return vault() / INFERENCES / f"{slug}.md"


def _load_inference(slug):
    p = inference_path(slug)
    if not p.exists():
        raise MemError(f"no inference record '{slug}' in {INFERENCES}/")
    meta, body = util.parse_frontmatter(util.read_text(p))
    return p, meta, body


def infer(kind, title, scope=None, slug=None, text=None, related=None, force=False):
    if kind not in ("observation", "claim"):
        raise MemError("kind must be 'observation' or 'claim'")
    _check_no_timestamp(title, "title")
    if kind == "claim" and scope not in ("project", "person"):
        # No default on purpose: a default would silently decide who may
        # promote the claim.
        raise MemError("a claim needs --scope project (about a system; an agent may "
                       "promote it after fresh verification) or --scope person (about "
                       "the user; only the user may confirm it).")
    slug = util.slugify(slug or title)
    p = inference_path(slug)
    if p.exists():
        raise MemError(f"record '{slug}' exists; add to it instead of duplicating")
    if not force:
        hit = similar_name(slug, vault() / INFERENCES)
        if hit:
            raise DuplicateError(f"a similar record exists: {rel(hit)}. Read it and add "
                                 "to it, or pass --force if it is really different.")
    meta = {"title": title, "kind": kind,
            "status": "observation" if kind == "observation" else "unverified",
            "scope": scope or "-", "created": util.stamp(), "updated": util.stamp(),
            "source": "claude-code"}
    if kind == "observation":
        body = f"# {title}\n\n## Observation\n\n{text or ''}\n\n"
    else:
        body = (f"# {title}\n\n## Claim\n\n{text or ''}\n\n## Evidence\n\n\n"
                "## Not tested\n\n\n")
    body += f"Related: [[{related}]]\n" if related else "Related: \n"
    util.write_text(p, util.render_frontmatter(meta) + body)
    return p


def _append_section(path, heading, text):
    content = util.read_text(path).rstrip("\n")
    util.write_text(path, content + f"\n\n## {heading} ({util.stamp()})\n\n{text}\n")


def verify(slug, evidence):
    p, meta, _ = _load_inference(slug)
    st = meta.get("status")
    if st != "unverified":
        raise MemError(f"'{slug}' is {st}; only an unverified claim can be verified")
    evidence = " ".join((evidence or "").split())
    if len(evidence) < 20:
        raise MemError("--evidence must say what you re-measured and how (at least "
                       "20 characters). Re-reading the same notes is not verification.")
    _append_section(p, "Verification", evidence)
    util.update_frontmatter(p, status="verified", verified=util.stamp(),
                            updated=util.stamp())
    return p


def resolve_note(target):
    """`topics/x`, `topics/x.md` or a unique basename -> Path or None."""
    target = target.strip()
    root = vault()
    for cand in (root / target, root / f"{target}.md"):
        if cand.is_file():
            return cand
    name = Path(target).name
    name = name if name.endswith(".md") else f"{name}.md"
    hits = [p for p in iter_notes(root) if p.name == name
            and INFERENCES not in p.relative_to(root).parts]
    if len(hits) > 1:
        raise MemError(f"'{target}' is ambiguous: " + ", ".join(rel(h) for h in hits))
    return hits[0] if hits else None


def has_heading(path, section):
    want = util.fold(section).strip()
    for line in util.read_text(path).splitlines():
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m and want in util.fold(m.group(1)):
            return True
    return False


def promote(slug, target, user_confirmed=False):
    p, meta, _ = _load_inference(slug)
    st = meta.get("status")
    if st != "verified":
        raise MemError(f"'{slug}' is {st}. Promotion needs a fresh verification first: "
                       f"mem verify {slug} --evidence \"what you re-measured, how\"")
    try:
        age = (util.now() - util.datetime.strptime(meta.get("verified", ""),
                                                   "%Y-%m-%d %H:%M")).days
    except ValueError:
        age = 10 ** 6
    if age > VERIFY_FRESH_DAYS:
        raise MemError(f"the verification is {age} days old (limit {VERIFY_FRESH_DAYS}); "
                       "re-verify before promoting")
    if meta.get("scope") == "person" and not user_confirmed:
        raise MemError("this claim is about the user (scope: person); only the user may "
                       "confirm it. Ask them, then pass --user-confirmed.")
    note, _, section = target.partition("#")
    path = resolve_note(note)
    # The gate: the promoted knowledge must already live somewhere. Without it
    # a record can point at a section that was never written.
    if not path:
        raise MemError(f"target note '{note}' does not exist. Write the knowledge "
                       "into the permanent note first, then promote.")
    if section and not has_heading(path, section):
        raise MemError(f"'{rel(path)}' has no heading matching '{section}'. Write that "
                       "section first, then promote.")
    dest = rel(path) + (f"#{section}" if section else "")
    _append_section(p, "Promoted", f"Now lives in [[{dest}]]. This record only shows "
                    "where the knowledge came from; rely on the permanent note.")
    util.update_frontmatter(p, status="promoted", promoted_to=dest, promoted=util.stamp(),
                            updated=util.stamp())
    return p, dest


def refute(slug, reason):
    p, meta, _ = _load_inference(slug)
    st = meta.get("status")
    if st in ("refuted",):
        raise MemError(f"'{slug}' is already refuted")
    if st == "promoted":
        raise MemError(f"'{slug}' is promoted; fix the permanent note "
                       f"({meta.get('promoted_to')}) first, then refute")
    reason = " ".join((reason or "").split())
    if not reason:
        raise MemError("--reason is required")
    # Refuted records are kept: they are what stops the same wrong inference
    # from being made again.
    _append_section(p, "Refuted", reason)
    util.update_frontmatter(p, status="refuted", refuted=util.stamp(), updated=util.stamp())
    return p


def list_inferences(status=None):
    d = vault() / INFERENCES
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.md")):
        meta, _ = util.parse_frontmatter(util.read_text(p))
        if status and meta.get("status") != status:
            continue
        out.append({"slug": p.stem, "title": meta.get("title", p.stem),
                    "status": meta.get("status", "?"), "scope": meta.get("scope", "-"),
                    "created": meta.get("created", ""), "path": p})
    return out


# ----------------------------------------------------------------- notes

_STOP = {"and", "the", "of", "a", "an", "for", "to", "in", "on", "with", "notes", "note"}


def _name_tokens(name):
    toks = [t for t in re.split(r"[^a-z0-9]+", util.fold(name)) if t and t not in _STOP]
    return set(toks)


def similar_name(name, scope=None):
    """A passive 'append, don't duplicate' rule never fires: writing is cheap
    and searching is vague. This is a deliberately dumb name-token check."""
    new = _name_tokens(Path(name).stem)
    new_slug = util.slugify(Path(name).stem)
    best = None
    for p in iter_notes(scope or vault()):
        if p.name in (CONTRACT, INDEX, "README.md"):
            continue
        if util.slugify(p.stem) == new_slug:
            return p
        old = _name_tokens(p.stem)
        if not new or not old:
            continue
        # "date" and "dates" are the same word for this purpose.
        share = sum(1 for a in new if any(a == b or (min(len(a), len(b)) >= 4 and
                                                     (a.startswith(b) or b.startswith(a)))
                                          for b in old))
        ratio = share / min(len(new), len(old))
        if share >= 2 and ratio >= 0.6 and (best is None or ratio > best[0]):
            best = (ratio, p)
    return best[1] if best else None


def note_new(folder, name, title=None, trigger=None, force=False, tags=""):
    folder = folder.strip("/\\").replace("\\", "/")
    parts = folder.split("/")
    if not folder or ".." in parts or parts[0] in SYSTEM_DIRS or len(parts) > 2:
        raise MemError(f"'{folder}' is not a note folder. Use topics, projects, "
                       "projects/<name>, or another top-level folder you created. "
                       "System folders are written by their own commands.")
    if any(c in name for c in "/\\") or name.startswith(".") or not name.strip():
        raise MemError("note name must be a plain file name")
    _check_no_timestamp(title or "", "title")
    path = vault() / folder / (name if name.endswith(".md") else f"{name}.md")
    if path.exists():
        raise MemError(f"{rel(path)} exists: append to it instead")
    if not force:
        hit = similar_name(path.name)
        if hit:
            raise DuplicateError(f"a similar note exists: {rel(hit)}. Read it and append "
                                 "there, or pass --force if it is really a new topic.")
    title = title or path.stem.replace("_", " ").replace("-", " ")
    meta = {"title": title, "created": util.stamp(), "updated": util.stamp(),
            "source": "claude-code", "tags": [t.strip() for t in tags.split(",") if t.strip()]}
    util.write_text(path, util.render_frontmatter(meta) + f"# {title}\n\n")
    if trigger:
        add_index_line(rel(path)[:-3], trigger)
    return path


def add_index_line(link, trigger):
    _check_no_timestamp(trigger, "trigger")
    idx = vault() / INDEX
    line = f"- [[{link}]] — {' '.join(trigger.split())}\n"
    text = util.read_text(idx) if idx.exists() else "# Index\n\n"
    util.write_text(idx, text.rstrip("\n") + "\n" + line)
    return line.strip()


INDEX_LINE_RE = re.compile(r"^\s*[-*]\s*\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]\s*[—–-]*\s*(.*)$")


def index_lines():
    """[(link, trigger_text, raw_line)] from INDEX.md."""
    idx = vault() / INDEX
    if not idx.exists():
        return []
    out = []
    for line in util.read_text(idx).splitlines():
        m = INDEX_LINE_RE.match(line)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip(), line.strip()))
    return out


def priority_lines():
    return [raw for _, trig, raw in index_lines() if PRIORITY_TOKEN.lower() in raw.lower()]
