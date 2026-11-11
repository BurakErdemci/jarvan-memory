"""`mem`: the single writer for the memory vault.

Every command that writes stamps its own dates. Errors are printed as one
plain sentence that says what to do instead, with exit code 1 (3 for a
duplicate-name refusal).
"""
import argparse
import json
import sys

from . import __version__, util, vault as V


def _p(path):
    return V.rel(path)


def cmd_log(a):
    util.out(V.log(a.text, a.next, a.handoff, a.done, a.project))


def cmd_handoff(a):
    if a.action == "open":
        p = V.handoff_open(a.title, a.slug, a.project)
        util.out(f"{_p(p)}\nFill all five sections now (zero-context test: could an agent "
                 "with no memory of this session take the first step from it?).")
    elif a.action == "close":
        util.out(_p(V.handoff_close(a.slug)))
    else:
        hs = V.open_handoffs()
        if not hs:
            util.out("No open handoffs.")
        for h in hs:
            util.out(f"- {h['project']} · {V.HANDOFFS}/{h['slug']}.md · {h['title']} "
                     f"(opened {h['created']})")


def cmd_infer(a):
    if a.kind == "list":
        rows = V.list_inferences(a.status)
        if not rows:
            util.out("No records.")
        for r in rows:
            util.out(f"- {r['status']:<11} {r['scope']:<7} {r['slug']} · {r['title']}")
        return
    if not a.title:
        raise V.MemError("a title is required")
    p = V.infer(a.kind, a.title, a.scope, a.slug, a.text, a.related, a.force)
    util.out(f"{_p(p)}\nFill the body: what was seen, measured how, and what was NOT tested. "
             "Link the topic note on the Related line.")


def cmd_verify(a):
    util.out(f"verified: {_p(V.verify(a.slug, a.evidence))}")


def cmd_promote(a):
    p, dest = V.promote(a.slug, a.to, a.user_confirmed)
    util.out(f"promoted: {_p(p)} -> {dest}")


def cmd_refute(a):
    util.out(f"refuted (kept on record): {_p(V.refute(a.slug, a.reason))}")


def cmd_note(a):
    p = V.note_new(a.folder, a.name, a.title, a.trigger, a.force)
    msg = _p(p)
    if not a.trigger:
        msg += ("\nAdd a trigger line so the note can be found: "
                f"mem index add {_p(p)[:-3]} \"<words/questions that should lead here>\"")
    util.out(msg)


def cmd_index(a):
    util.out(V.add_index_line(a.link, a.trigger))


def cmd_search(a):
    from . import search
    res = search.search(" ".join(a.query), k=a.k)
    if a.json:
        util.out(json.dumps([{k: r[k] for k in ("path", "start", "end", "heading", "status", "lines")}
                             for r in res], ensure_ascii=False, indent=1))
        return
    if not res:
        util.out("No match in the vault (searched with `mem search`, full-text over all notes "
                 "except worklog/daily). Absence after one query is not proof: try other words.")
        return
    util.out(search.format_results(res))


def cmd_reindex(a):
    from . import search
    p = search.db_path(util.vault_dir())
    for suffix in ("", "-wal", "-shm"):
        util.Path(str(p) + suffix).unlink(missing_ok=True)
    con = search.update_index()
    n = con.execute("SELECT count(*) FROM sections").fetchone()[0]
    con.close()
    util.out(f"indexed {n} sections")


def cmd_status(a):
    cfg = util.load_config()
    util.out(f"vault: {cfg['vault']}")
    util.out(f"modules: {', '.join(cfg.get('modules') or []) or 'none'}")
    hs = V.open_handoffs()
    util.out(f"open handoffs: {len(hs)}")
    infs = V.list_inferences()
    for st in V.STATUSES:
        n = sum(1 for i in infs if i["status"] == st)
        if n:
            util.out(f"inferences {st}: {n}")
    tail = V.read_worklog()[-3:]
    if tail:
        util.out("last worklog lines:")
        for e in tail:
            util.out(f"  - {e['ts']} · {e['kind']} · {e['project']} · {e['body'][:120]}")


def cmd_doctor(a):
    from . import doctor
    return doctor.main(json_out=a.json)


def cmd_uninstall(a):
    from . import installer
    return installer.uninstall(purge_vault=a.purge_vault, yes=a.yes)


def cmd_repair_python(a):
    from . import installer
    return installer.repair_python(a.python)


def cmd_sweep(a):
    from . import jobs
    jobs.run_sweep(util.load_config(), force=True)
    util.out("sweep finished; see the sweeps/ folder and `mem doctor` for errors")


def build_parser():
    ap = argparse.ArgumentParser(prog="mem", description="jarvan-memory: persistent memory "
                                 "for Claude Code. Dates are always stamped by this command.")
    ap.add_argument("--version", action="version", version=f"jarvan-memory {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("log", help="append a worklog line (a pointer, max 200 chars)")
    s.add_argument("text")
    s.add_argument("--next", help="the concrete first step for whoever continues")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--handoff", metavar="SLUG", help="work is carried over in this handoff")
    g.add_argument("--done", action="store_true", help="nothing is left open")
    s.add_argument("--project")
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("handoff", help="open, close or list handoff notes")
    hs = s.add_subparsers(dest="action", required=True)
    o = hs.add_parser("open")
    o.add_argument("title")
    o.add_argument("--slug")
    o.add_argument("--project")
    c = hs.add_parser("close")
    c.add_argument("slug")
    hs.add_parser("list")
    s.set_defaults(fn=cmd_handoff)

    s = sub.add_parser("infer", help="record an observation or claim in quarantine, or list them")
    s.add_argument("kind", choices=["observation", "claim", "list"])
    s.add_argument("title", nargs="?")
    s.add_argument("--scope", choices=["project", "person"])
    s.add_argument("--slug")
    s.add_argument("--text", help="first paragraph of the body")
    s.add_argument("--related", help="topic note to link, e.g. topics/Build")
    s.add_argument("--status", choices=list(V.STATUSES), help="filter for `list`")
    s.add_argument("--force", action="store_true", help="create despite a similar name")
    s.set_defaults(fn=cmd_infer)

    s = sub.add_parser("verify", help="mark a claim verified after a FRESH check")
    s.add_argument("slug")
    s.add_argument("--evidence", required=True, help="what you re-measured, how")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("promote", help="mark a verified claim as moved into a permanent note")
    s.add_argument("slug")
    s.add_argument("--to", required=True, metavar="NOTE[#SECTION]")
    s.add_argument("--user-confirmed", action="store_true",
                   help="required for scope: person (the user confirmed it)")
    s.set_defaults(fn=cmd_promote)

    s = sub.add_parser("refute", help="mark a record refuted (it is kept)")
    s.add_argument("slug")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_refute)

    s = sub.add_parser("note", help="create a note with generated frontmatter")
    ns = s.add_subparsers(dest="action", required=True)
    n = ns.add_parser("new")
    n.add_argument("folder", help="topics, projects, projects/<name>, ...")
    n.add_argument("name", help="file name without .md")
    n.add_argument("--title")
    n.add_argument("--trigger", help="INDEX trigger: words/questions that should lead here")
    n.add_argument("--force", action="store_true", help="create despite a similar name")
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser("index", help="add an INDEX trigger line")
    xs = s.add_subparsers(dest="action", required=True)
    x = xs.add_parser("add")
    x.add_argument("link", help="note path without .md, e.g. topics/Build")
    x.add_argument("trigger")
    s.set_defaults(fn=cmd_index)

    s = sub.add_parser("search", help="search notes: path, line range, matching lines")
    s.add_argument("query", nargs="+")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_search)

    sub.add_parser("reindex", help="rebuild the search index").set_defaults(fn=cmd_reindex)
    sub.add_parser("status", help="vault summary").set_defaults(fn=cmd_status)

    s = sub.add_parser("doctor", help="check the installation end to end")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("uninstall", help="remove what the installer added (keeps the vault)")
    s.add_argument("--purge-vault", action="store_true", help="legacy option; refused to protect the vault")
    s.add_argument("--yes", action="store_true", help="legacy purge confirmation (vault is always kept)")
    s.set_defaults(fn=cmd_uninstall)

    s = sub.add_parser("repair-python", help="re-detect the Python interpreter for the hooks")
    s.add_argument("--python", help="absolute path of the interpreter to use")
    s.set_defaults(fn=cmd_repair_python)

    sub.add_parser("sweep", help="run the quarantine sweep now (optional module)").set_defaults(fn=cmd_sweep)
    return ap


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    a = build_parser().parse_args(argv)
    try:
        rc = a.fn(a)
    except V.MemError as e:
        util.err(f"mem: {e}")
        return e.code
    except util.NotInstalled as e:
        util.err(f"mem: {e}")
        return 1
    except json.JSONDecodeError as e:
        util.err(f"mem: invalid JSON in configuration or state: {e}. Repair the file and retry.")
        return 1
    except OSError as e:
        util.err(f"mem: {e}")
        return 1
    return rc or 0
