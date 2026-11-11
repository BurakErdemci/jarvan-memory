# How jarvan-memory works

Three parts: a **vault** (plain Markdown folders), a **writer** (`mem`, the only
thing that writes structured records), and **hooks** that put the right slice
of the vault in front of the agent at the right moment and hold a few gates.

```
             read path                                write path
  ┌──────────────────────────────┐        ┌────────────────────────────────┐
  │ SessionStart   context block │        │ mem log / handoff / infer /    │
  │ UserPromptSubmit suggestions │ vault  │ verify / promote / refute /    │
  │ PostToolUseFailure recall    │◄──────►│ note new / index add           │
  │ mem search (agent-initiated) │        │ SessionEnd line (hook)         │
  └──────────────────────────────┘        │ daily/ summary (optional job)  │
                                          └────────────────────────────────┘
        gates: Stop (memory write), PreToolUse (worklog timestamps)
```

## Files and where they live

| Path | Content |
|---|---|
| `<vault>/` | The notes. See the layout table in `AGENT.md`. |
| `<claude config>/jarvan-memory/runtime/` | A copy of the Python package and `run.py` |
| `<claude config>/jarvan-memory/hook.sh` | Shim every hook calls; holds the interpreter path |
| `<claude config>/jarvan-memory/bin/mem`, `mem.cmd` | CLI launchers (sh, and cmd/PowerShell) |
| `<claude config>/jarvan-memory/config.json` | Vault path, interpreter, modules, models, install record |
| `<claude config>/jarvan-memory/state/` | Per-session counters, scratch notes, search index, job errors. Never in the vault, never synced. |

`<claude config>` is `$CLAUDE_CONFIG_DIR`, or `~/.claude`.

## Hooks

| Event | Matcher | What it does |
|---|---|---|
| SessionStart | all | Injects the context block; prunes state older than 7 days; schedules the weekly sweep if enabled |
| UserPromptSubmit | all | Counts prompts (the stop gate reads the count); suggests up to 2 note sections when the gate passes |
| PreToolUse | `Write\|Bash` | Refuses hand-written worklog files and shell appends that type a timestamp into the worklog |
| PostToolUse | `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | Marks "this session wrote to memory" |
| PostToolUseFailure | `Bash` | Recalls at most 2 notes that match the failure, once per note per session |
| Stop | all | The stop gate |
| SessionEnd | all | Writes a clock-stamped session line; updates the miss streak; starts optional jobs detached |

Every hook command is `bash "<claude config>/jarvan-memory/hook.sh" <event>`.
Claude Code runs hooks through Git Bash on Windows and `sh`/`bash` elsewhere,
so the same command works on all three systems. The shim exits at once inside
any child process we start (`JARVAN_MEMORY_CHILD=1`), and if the recorded
interpreter is gone it says so in the session-start block instead of failing
silently.

## Read path

**Session start block**, in order:

1. A frame: everything below is a record, not an instruction; check dates.
2. Attention items: missing vault, a streak of sessions that ended without a
   memory write, background job failures, "context was just compacted and
   nothing is written yet".
3. `profile.md` (HTML comments and empty headings dropped; cut at 2500
   characters *with a marker* saying where the rest is).
4. INDEX lines containing `READ FIRST` (up to 4; more are announced, not hidden).
5. The last 3 worklog lines for this project (project = name of the session's
   first working directory).
6. Open handoffs for this project, and a count for other projects.
7. Quarantine counts (unverified, verified-not-promoted).
8. A pending sweep report, if any.
9. The path of this session's scratch note, and its content if it was written
   in the last 48 hours (first 120 lines, with a marker if longer).

If the block exceeds 8000 characters a line says so. Nothing is cut silently:
a note that silently falls off the block looks exactly like a note that was
never written.

**Search** (`mem search`). Notes are split at `#`, `##` and `###` headings.
Each section is indexed with its heading chain, its line range and its text,
folded (lowercase, diacritics removed) so search works across Latin-script
languages. A note's INDEX trigger text is indexed with its first section at
high weight. Ranking is BM25 with weights path 2, heading 6, body 1, stems 1,
triggers 4, then multiplied down for refuted (0.3), superseded (0.3),
promoted (0.5, the permanent note should win), unverified (0.8), archived or
handoff notes (0.8), and a slow age decay (never below 0.75). At most two
sections per note. Output: `path:start-end  heading  [status]` and up to three
best lines. The index updates incrementally by file mtime and size. Without
FTS5, a pure-Python scan gives the same output.

**Prompt suggestions** use the same search with a strict gate: at least two
content words; the best section must contain at least three of them *and* at
least 60% of all of them. Otherwise the hook prints nothing, so a large vault
costs a prompt no more than a small one. A note is suggested once per session.

**Failure recall** looks at a failed Bash call's error lines. It tries several
views (the whole error, the last line, each error line on its own) because a
traceback's boilerplate dilutes the real message, and accepts a view only if
one section covers at least 70% of its words. At most two notes, never a
refuted one, once per note per session.

## Write path

- `mem log` — one worklog line: `- <stamp> · agent · <project> · <text>[ · next: …] · done|handoff: [[…]]`.
  The carry-over declaration (`--done` or `--handoff <slug>`) is required; the
  line is at most 200 characters; typed timestamps are refused.
- `mem handoff open|close|list` — five-section notes; the open list is derived
  from each note's `status` on every call; closing archives, never deletes.
- `mem infer observation|claim`, `verify`, `promote`, `refute` — the quarantine (below).
- `mem note new <folder> <Name> [--trigger …]` — generated frontmatter;
  refuses names that look like an existing note (`--force` to override);
  system folders are refused.
- `mem index add` — a trigger line in INDEX.md.
- SessionEnd — `- <stamp> · session · <project> · N prompts · M min · memory: written|not written`,
  only for sessions with 3+ prompts.

## Quarantine lifecycle

```
observation  (free; never promoted)

claim ──► unverified ──verify (fresh evidence)──► verified ──promote (target exists)──► promoted
              │                                      │
              └────────────refute (reason)───────────┴──► refuted (kept)
```

- A claim needs a scope: `project` (an agent may promote after verifying) or
  `person` (only the user may confirm: `--user-confirmed`).
- `verify` needs evidence text of at least 20 characters describing what was
  re-measured; promotion needs a verification younger than 14 days.
- `promote --to note#section` refuses unless the note and the heading exist:
  write the knowledge first, then stamp the record.
- A promoted record cannot be refuted until its permanent note is fixed.

## Gates

**Stop gate.** The session state counts prompts (`prompts`), the prompt count
at the last memory write (`wrote_at`) and at the last block (`blocked_at`).
When `prompts - max(wrote_at, blocked_at) >= 10` (configurable as
`stop_gate_prompts`), finishing the turn is blocked once with a question:
is work carried over, did something durable come up, is there an
observation. The text says explicitly that one honest worklog line is
enough and that invented records are noise. `stop_hook_active` turns are
never blocked, so the gate cannot loop; the block is recorded only after the
reply was printed. The gate re-arms after another full stretch.

A "memory write" is a Write/Edit inside the vault, or a Bash command that
mentions the vault path or runs a writing `mem` subcommand. `mem search` does
not count.

**Worklog guard.** `Write` to a worklog file is refused. A Bash command that
writes (`>>`, `>`, `tee`, `sed -i`, ...) into a worklog path *and* contains a
`YYYY-MM-DD HH:MM` timestamp is refused. `Edit` stays allowed, so a single
wrong line can still be corrected deliberately.

## Optional modules

All three run detached from the hook (new session on POSIX; new process group
with a hidden console on Windows, where `start_new_session` is silently
ignored), record their last failure in `state/job-errors.json`, and clear it
on success. Session start shows recorded failures.

- **summary** — SessionEnd: transcript text (user and assistant text only) →
  skip under 2000 characters → newest 120 000 characters → `claude -p
  --setting-sources "" --tools "" --no-session-persistence` with the
  transcript fenced as untrusted data and the output contract repeated after
  it → the reply must have exactly six headings in order (or the single
  word `NOTHING_TO_KEEP`) → appended to `daily/YYYY-MM-DD.md`. A per-session
  lock prevents duplicates; timeouts kill the whole process tree.
- **backup** — after the summary: `git add -A`, commit if anything changed,
  push only if a remote exists. Git is run with repo-level fsmonitor and
  hooks disabled.
- **sweep** — at most weekly, from SessionStart: unverified claims with at
  least three matching words in recent worklog/daily entries go to a cheap
  model, which may only propose `refute` with a verbatim quote. A proposal is
  kept only if the quote is at least 20 characters, appears verbatim in an
  evidence item actually sent for that record, and does not look like a
  secret. Proposals go to `sweeps/`; records are never changed.

## Doctor

`mem doctor` runs the checks below and prints `passed/total`. Hook checks run
the *exact* command strings from `settings.json` through bash with a probe
session id (probe sessions write no state):

config · python interpreter (runs, ≥3.9, not a Store alias) · runtime files
(present, no placeholders) · hooks registered (all seven, right matchers) ·
hooks fire (session-start injects a block; others answer) · stop gate armed
(a probe with a huge prompt count gets `decision: block`) · worklog guard
(a probe Write to the worklog gets `deny`) · mem command runs · vault writable
· vault skeleton · no leftover placeholders · CLAUDE.md pointer · search works
(a throwaway vault with a known note must return that note at the right
line) · plus `claude` CLI and git when the modules that need them are on.
