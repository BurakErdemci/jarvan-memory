"""Section-level full-text search over the vault (SQLite FTS5, stdlib only).

Notes are split into sections at #, ## and ### headings; every result is a
note path, a line range and the best matching lines, so the agent reads only
that range instead of whole files. Text is folded (lowercase, diacritics
stripped) before indexing, which makes search work for any Latin-script
language. If the local SQLite has no FTS5, a slower pure-Python scan with the
same output is used.
"""
import hashlib
import math
import re
import sqlite3
import time
from pathlib import Path

from . import util, vault as V

SCHEMA = "5"
# Hooks must answer inside their own timeout (10 s). Indexing a big vault
# from cold takes longer, so a hook indexes for at most this long, stays
# silent for that prompt and carries on at the next call.
HOOK_INDEX_BUDGET = 3.0
# Not searched: raw logs and machine output. Worklog lines are pointers and
# daily summaries are distilled copies; both would outrank the real notes.
EXCLUDE_TOP = {V.WORKLOG, V.DAILY, V.TEMPLATES, V.SWEEPS}
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
STOPWORDS = set(util.fold(w) for w in """
a an and are as at be by can do does for from how i in is it me my of on or
our that the this to was we what when where which who why will with you your
about into should would could did done have has had there their them then
ve ile bir bu de da mi mu ne nasil neden niye icin gibi daha cok kadar ben
sen biz siz o su ki ya ama veya hangi nerede zaman olan oldu var yok
""".split())

_fts5_cache = {}


def fts5_available():
    if "ok" not in _fts5_cache:
        try:
            c = sqlite3.connect(":memory:")
            c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            c.close()
            _fts5_cache["ok"] = True
        except sqlite3.Error:
            _fts5_cache["ok"] = False
    return _fts5_cache["ok"]


def _stemmer(cfg):
    if (cfg or {}).get("stemmer") == "tr":
        from . import stem_tr
        return stem_tr.stem
    return None


def db_path(root):
    h = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:12]
    return util.state_dir() / f"search-{h}.sqlite"


# ----------------------------------------------------------------- indexing

def split_sections(text, fallback_title):
    """[(heading_chain, start_line, end_line, body, body_start)], 1-based.
    Sections with an empty body are skipped."""
    meta, _ = util.parse_frontmatter(text)
    # Only "\n" ends a line: str.splitlines also splits on U+2028, form feed
    # and others, which an editor and the Read tool do not count.
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    start = 0
    if text.startswith("---"):
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    sections, chain = [], []
    cur_head, cur_start, buf = meta.get("title") or fallback_title, start + 1, []
    heading_line = False

    def flush(end):
        body = "\n".join(buf)
        if body.strip():
            bstart = cur_start + (1 if heading_line else 0)
            sections.append((cur_head, cur_start, max(cur_start, end), body, bstart))

    for i in range(start, len(lines)):
        m = HEADING_RE.match(lines[i])
        if m:
            flush(i)
            level = len(m.group(1))
            chain = chain[: level - 1] + [m.group(2)]
            cur_head, cur_start, buf = " > ".join(chain), i + 1, []
            heading_line = True
        else:
            buf.append(lines[i])
    flush(len(lines))
    return sections, meta


def _connect(path):
    con = sqlite3.connect(str(path), timeout=0.5)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _create(con, fts):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER, trig TEXT);
    CREATE TABLE IF NOT EXISTS sections(id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT, heading TEXT, start INTEGER, end INTEGER, body TEXT,
        status TEXT, mtime REAL, bstart INTEGER, fheading TEXT, fbody TEXT, stems TEXT, triggers TEXT);
    CREATE INDEX IF NOT EXISTS sections_path ON sections(path);
    """)
    if fts:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5("
                    "path, heading, body, stems, triggers, "
                    "tokenize='unicode61 remove_diacritics 2', prefix='2 3 4 5')")


def _wanted_files(root):
    root = Path(root)
    for p in V.iter_notes(root):
        parts = p.relative_to(root).parts
        if parts and parts[0] in EXCLUDE_TOP:
            continue
        if parts == (V.INDEX,):
            continue  # its trigger lines are indexed into the notes they name
        if p.is_symlink():
            continue
        yield p


def _triggers(root):
    out = {}
    idx = Path(root) / V.INDEX
    if not idx.exists():
        return out
    for line in util.read_text(idx).splitlines():
        m = V.INDEX_LINE_RE.match(line)
        if m:
            key = m.group(1).strip().removesuffix(".md")
            out[util.fold(key)] = out.get(util.fold(key), "") + " " + m.group(2)
            out.setdefault(util.fold(Path(key).name), out[util.fold(key)])
    return out


def update_index(root=None, cfg=None, budget=None):
    """Incremental: re-index files whose (mtime, size, trigger text) changed.
    Returns the open connection. If another process holds the write lock, the
    last committed index is used as is. With a `budget` in seconds, stops
    when it is spent, commits what fit and marks the index incomplete (see
    `is_complete`); the next call continues where this one stopped."""
    cfg = cfg if cfg is not None else util.load_config(required=False)
    root = Path(root or util.vault_dir(cfg))
    stem = _stemmer(cfg)
    fts = fts5_available()
    path = db_path(root)
    con = _connect(path)
    sig = f"{SCHEMA}|fts={int(fts)}|stem={cfg.get('stemmer') or '-'}|{root.resolve()}"
    _create(con, fts)
    row = con.execute("SELECT value FROM meta WHERE key='sig'").fetchone()
    if not row or row[0] != sig:
        con.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
        con = _connect(path)
        _create(con, fts)
        con.execute("INSERT OR REPLACE INTO meta VALUES('sig', ?)", (sig,))
        con.commit()
    triggers = _triggers(root)
    try:
        con.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        return con
    deadline = time.time() + budget if budget else None
    try:
        known = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT * FROM files")}
        seen = set()
        complete, indexed = True, 0  # at least one file per call: always progress
        for p in _wanted_files(root):
            r = p.relative_to(root).as_posix()
            seen.add(r)
            st = p.stat()
            trig = _trigger_for(triggers, r, p)
            sig = hashlib.sha256(trig.encode()).hexdigest()[:16]
            if known.get(r) == (st.st_mtime_ns, st.st_size, sig):
                continue
            if deadline and indexed and time.time() > deadline:
                complete = False
                continue
            _drop(con, r, fts)
            _index_file(con, root, p, r, st, stem, trig, sig, fts)
            indexed += 1
        if complete:
            for r in set(known) - seen:
                _drop(con, r, fts)
                con.execute("DELETE FROM files WHERE path=?", (r,))
        con.execute("INSERT OR REPLACE INTO meta VALUES('complete', ?)", (str(int(complete)),))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return con


def is_complete(con):
    """False while a budgeted update_index still has files left to index."""
    row = con.execute("SELECT value FROM meta WHERE key='complete'").fetchone()
    return bool(row) and row[0] == "1"


def _trigger_for(triggers, r, p):
    return triggers.get(util.fold(r[:-3]), "") or triggers.get(util.fold(p.stem), "")


def _drop(con, r, fts):
    if fts:
        con.execute("DELETE FROM search WHERE rowid IN (SELECT id FROM sections WHERE path=?)", (r,))
    con.execute("DELETE FROM sections WHERE path=?", (r,))


def _index_file(con, root, p, r, st, stem, trig, sig, fts):
    secs, meta = split_sections(util.read_text(p), p.stem.replace("_", " "))
    status = meta.get("status", "")
    fpath = util.fold(r[:-3]).replace("_", " ").replace("/", " ")
    for i, (head, s, e, body, bstart) in enumerate(secs):
        fh, fb = util.fold(head), util.fold(body)
        stems = " ".join(stem(w) for w in util.words(head + " " + body)) if stem else ""
        t = util.fold(trig) if i == 0 else ""
        cur = con.execute(
            "INSERT INTO sections(path,heading,start,end,body,status,mtime,bstart,fheading,fbody,"
            "stems,triggers) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (r, head, s, e, body, status, st.st_mtime, bstart, fh, fb, stems, t))
        if fts:
            con.execute("INSERT INTO search(rowid,path,heading,body,stems,triggers) VALUES(?,?,?,?,?,?)",
                        (cur.lastrowid, fpath, fh, fb, stems, t))
    con.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)",
                (r, st.st_mtime_ns, st.st_size, sig))


# ----------------------------------------------------------------- querying

def query_terms(text, max_terms=40):
    seen, terms = set(), []
    for w in util.words(text):
        if len(w) < 2 or w in STOPWORDS or w.isdigit():
            continue
        t = w[: max(5, len(w) - 3)] if len(w) >= 6 else w
        if t not in seen:
            seen.add(t)
            terms.append((t, w))
    terms.sort(key=lambda x: -len(x[1]))
    return terms[:max_terms]


def _weight(status, heading, mtime, path):
    w = 1.0
    if status == "refuted":
        w *= 0.3
    elif status == "promoted":
        # The knowledge now lives in a permanent note; that note should win.
        w *= 0.5
    elif status in ("unverified", "observation"):
        w *= 0.8
    if "superseded" in util.fold(heading):
        w *= 0.3
    if path.startswith(V.ARCHIVE + "/") or path.startswith(V.HANDOFFS + "/"):
        w *= 0.8
    months = max(0.0, (time.time() - (mtime or 0)) / (30 * 86400))
    return w * max(0.75, 1 / (1 + 0.03 * months))


def _matched(terms, stems, text):
    toks = set(util.words(text))
    hit = set()
    for t, w in terms:
        if any(tok.startswith(t) for tok in toks):
            hit.add(t)
        elif stems and stems.get(w) and any(tok.startswith(stems[w]) for tok in toks):
            hit.add(t)
    return hit


def _best_lines(terms, body_lines, start, n=3):
    scored = []
    for i, line in enumerate(body_lines):
        toks = util.words(line)
        s = sum(1 for t, _ in terms if any(tok.startswith(t) for tok in toks))
        if s:
            scored.append((-s, i, line.strip()))
    scored.sort()
    return [(start + i, line[:200]) for _, i, line in scored[:n]]


def search(text, k=5, root=None, cfg=None, per_file=2, exclude=(), budget=None):
    """Best sections for `text`. With a `budget` (hooks), an index that could
    not be brought up to date inside it gives no answer at all: a partial
    index would suggest the wrong notes with confidence."""
    cfg = cfg if cfg is not None else util.load_config(required=False)
    root = Path(root or util.vault_dir(cfg))
    terms = query_terms(text)
    if not terms:
        return []
    stem = _stemmer(cfg)
    stems = {w: stem(w) for _, w in terms} if stem else {}
    con = update_index(root, cfg, budget=budget)
    try:
        if budget and not is_complete(con):
            return []
        if fts5_available():
            q = " OR ".join(f'"{t}"*' for t, _ in terms)
            if stems:
                q += " OR " + " OR ".join(f'stems:"{s}"' for s in sorted(set(stems.values())))
            rows = con.execute(
                "SELECT s.id, s.path, s.heading, s.start, s.end, s.body, s.status, s.mtime, s.bstart,"
                " s.triggers, -bm25(search, 2.0, 6.0, 1.0, 1.0, 4.0) FROM search JOIN sections s"
                " ON s.id = search.rowid WHERE search MATCH ? ORDER BY bm25(search, 2.0,"
                " 6.0, 1.0, 1.0, 4.0) LIMIT 100", (q,)).fetchall()
        else:
            rows = _scan(con, terms)
    finally:
        con.close()
    results = []
    for _id, path, head, s, e, body, status, mtime, bstart, trig, score in rows:
        if path in exclude:
            continue
        # INDEX trigger text counts toward the match, as AGENT.md promises.
        hit = _matched(terms, stems, head + "\n" + body + "\n" + (trig or ""))
        results.append({"path": path, "start": s, "end": e, "heading": head, "bstart": bstart,
                        "status": status, "body": body, "matched": hit,
                        "score": score * _weight(status, head, mtime, path)})
    results.sort(key=lambda r: -r["score"])
    out, per = [], {}
    for r in results:
        if per.get(r["path"], 0) >= per_file:
            continue
        per[r["path"]] = per.get(r["path"], 0) + 1
        r["lines"] = _best_lines(terms, r["body"].split("\n"), r["bstart"]) or [(r["start"], r["heading"])]
        out.append(r)
        if len(out) >= k:
            break
    for r in out:
        r["terms"] = len(terms)
    return out


def _scan(con, terms):
    """No-FTS5 fallback: idf-weighted prefix counts, heading x6, triggers x4."""
    rows = con.execute("SELECT id,path,heading,start,end,body,status,mtime,bstart,fheading,fbody,"
                       "triggers FROM sections").fetchall()
    n = max(1, len(rows))
    toks = [(r, set(util.words(r[9] + " " + r[10] + " " + (r[11] or "")))) for r in rows]
    df = {t: sum(1 for _, ts in toks if any(x.startswith(t) for x in ts)) for t, _ in terms}
    out = []
    for r, ts in toks:
        score = 0.0
        for t, _ in terms:
            if not df[t]:
                continue
            idf = math.log(1 + n / (df[t] + 0.5))
            if any(x.startswith(t) for x in util.words(r[9])):
                score += 6 * idf
            if any(x.startswith(t) for x in util.words(r[11] or "")):
                score += 4 * idf
            if any(x.startswith(t) for x in util.words(r[10])):
                score += idf
        if score:
            out.append(r[:9] + (r[11] or "", score))
    out.sort(key=lambda x: -x[10])
    return out[:100]


def format_results(results):
    lines = []
    for r in results:
        tag = f"  [{r['status']}]" if r["status"] else ""
        lines.append(f"{r['path']}:{r['start']}-{r['end']}  {r['heading']}{tag}")
        for n, text in r["lines"]:
            lines.append(f"  L{n}: {text}")
    return "\n".join(lines)
