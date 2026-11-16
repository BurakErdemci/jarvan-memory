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
| `<claude config>/jarvan-memory/state/hook-errors.log` | One line per failed hook run; shown at the next session start and by `mem doctor` |
| `<claude config>/jarvan-memory/bin/mem`, `mem.cmd` | CLI launchers (sh, and cmd/PowerShell) |
| `<claude config>/jarvan-memory/config.json` | Vault path, interpreter, modules, models, install record |
| `<claude config>/jarvan-memory/state/` | Per-session counters, scratch notes, search index, job errors. Never in the vault, never synced. |

`<claude config>` is `$CLAUDE_CONFIG_DIR`, or `~/.claude`.

## Hooks

| Event | Matcher | What it does |
|---|---|---|
| SessionStart | all | Injects the context block; prunes state older than 7 days; schedules the weekly sweep if enabled |
| UserPromptSubmit | all | Counts prompts (the stop gate reads the count); suggests up to 2 note sections when the gate passes |
| PreToolUse | `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | Refuses writes to the worklog folder by the file tools, and shell writes into it that type a timestamp |
| PostToolUse | `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | Marks "this session wrote to memory" |
| PostToolUseFailure | `Bash` | Recalls at most 2 notes that match the failure, once per note per session |
| Stop | all | The stop gate |
| SessionEnd | all | Writes a clock-stamped session line; updates the miss streak; starts optional jobs detached |

Every hook command is `bash '<claude config>/jarvan-memory/hook.sh' <event>`;
paths in the command, the shim and the `mem` launcher are single-quoted with
POSIX escaping, so a home folder with a space, `'`, `$` or a backtick works.
Claude Code runs hooks through Git Bash on Windows and `sh`/`bash` elsewhere,
so the same command works on all three systems. The shim is plain POSIX `sh`
and **always exits 0**: a non-zero exit from a hook makes Claude Code block
tool calls or the end of a turn, which a broken memory must never do. It exits
at once inside any child process we start (`JARVAN_MEMORY_CHILD=1`). If the
recorded interpreter or the runtime file is gone, or Python exits non-zero,
it appends a line to `state/hook-errors.log` and, at session start, says so in
the session-start block instead of failing silently.

Failures inside the Python handlers are logged the same way. The next session
start shows how many log lines are new since the last one (and the last
line); `mem doctor` shows a WARN for errors of the last 7 days.

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
high weight, and its words count as matched words for the suggestion gate. Ranking is BM25 with weights path 2, heading 6, body 1, stems 1,
triggers 4, then multiplied down for refuted (0.3), superseded (0.3),
promoted (0.5, the permanent note should win), unverified (0.8), archived or
handoff notes (0.8), and a slow age decay (never below 0.75). At most two
sections per note. Output: `path:start-end  heading  [status]` and up to three
best lines. The index updates incrementally by file mtime and size. Without
FTS5, a pure-Python scan gives the same output.

**Prompt suggestions** use the same search with a strict gate: at least three
content words; the best section (heading, body and its INDEX trigger text) must
contain at least three of them *and* at least 60% of all of them. Otherwise
the hook prints nothing, so a large vault costs a prompt no more than a small
one. A note is suggested once per session.

**Large vaults.** `install.py` builds the search index. A hook never spends
more than about 3 seconds indexing (`search.HOOK_INDEX_BUDGET`): if the index
is missing or stale beyond that, it indexes what fits, searches the sections
already committed, and carries on at the next call. Notes larger than 512 KiB
(524,288 bytes) are indexed only by the CLI; hooks skip them and continue with
smaller notes. A large deferred note never hides matches from indexed notes.
`mem search` always indexes fully, including oversized notes. Hook results may
omit notes still awaiting indexing.
Line numbers count only `\n` as a line break (not U+2028 or form feed), like an
editor and the Read tool.

**Failure recall** looks at a failed Bash call's error lines. It tries several
views (the whole error, the last line, each error line on its own) because a
traceback's boilerplate dilutes the real message, and accepts a view only if
one section covers at least 70% of its words. At most two notes, never a
refuted one, once per note per session.

## Write path

All writers share one vault lock (`state/vault.lock`, waited for up to 30
seconds; a timeout is an error, never a silent skip) and write through a temp
file plus `os.replace`, so parallel `mem` calls never lose a line. Every name
or path typed into a command must stay inside the vault folder it is meant for:
absolute paths, drive letters, `..`, separators in slugs, characters invalid on
Windows and system folder names (any letter case) are refused with a message.

- `mem log` — one worklog line: `- <stamp> · agent · <project> · <text>[ · next: …] · done|handoff: [[…]]`.
  The carry-over declaration (`--done` or `--handoff <slug>`) is required; the
  line is at most 200 characters; typed timestamps are refused in the text,
  `--next` and `--project`.
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
- `promote --to note#section` refuses unless the note and the heading exist
  (a section is at least 2 characters), and refuses a target in a system
  folder, the quarantine folder included: write the knowledge first, then stamp
  the record.
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

A "memory write" is a Write/Edit inside the vault, a Bash command whose
parsed write target (a `>`/`>>` redirect, `tee`, the target of `cp`, `mv` or
`rm`, `sed -i`) is inside the vault, or any command whose raw text holds the
`mem` launcher followed by a writing subcommand. The text rule is deliberate:
it is not a shell parser, so `echo "mem log x"` or a heredoc mentioning
`mem log` also counts. Trade-off: the gate errs toward counting a write, and
the only cost of a wrong count is one skipped reminder. Reading (`cat`,
`grep`) and `mem search` do not count. On Windows `/c/...` and `C:\...` name
the same file.

**Worklog guard.** Write, Edit, MultiEdit and NotebookEdit on a file inside
`<vault>/worklog/` are refused (a relative path is tested against the payload
`cwd` and against the vault root). A Bash command is looked at only when its
text holds a `YYYY-MM-DD HH:MM` timestamp *and* `worklog` as a path component
(a `/` or `\` right before or after it: `~/vault/worklog`, `$HOME/vault/worklog/a.md`,
`worklog/a.md`), or a bare `worklog` as the target of `cd`, `pushd`, `>`, `>>`,
`tee`, `cp` or `mv`. The vault path alone does not count, and neither does the word
on its own. Then it is refused outright when it holds a heredoc (`<<`), `$(`, a
backtick, `eval`, `xargs`, `env -...` or an interpreter followed directly by its exec
flag as a separate token (`bash -c`/`-lc`, `python -c`, `node -e`, `php -r`,
`pwsh -Command`, `cmd /c`); a path argument such as `bash /scripts/x.sh` or
`bash -e deploy.sh` is not an exec flag. Those forms hide the real command from any
parser. Otherwise the write targets are parsed (`cp -t DIR` and `--target-directory` included): the command is refused
when a target is inside `<vault>/worklog/` or cannot be resolved (an unset
variable, a `${X:-y}` expansion), and allowed when there is no target or every
target resolves outside. Trade-off: a wrong deny is accepted, but only for a
command that types both a timestamp and a worklog path; the guard does not chase new
shell syntax. A wrong old line is for the user to fix by hand.

The guard prevents accidents, not attacks. Its job is to catch an agent that
types a timestamp by hand; an agent writing to the worklog naturally names the
file path, and that case is always caught. It is not a security boundary: a
command built to hide its target (an exported variable, an unlisted
interpreter) can get past it, and there is nothing to gain by doing so, since
the vault belongs to the same user.

## Optional modules

All three run detached from the hook (new session on POSIX; new process group
with a hidden console on Windows, where `start_new_session` is silently
ignored), record their last failure in `state/job-errors.json`, and clear it
on success. Session start shows recorded failures.

- **summary** — SessionEnd: transcript text (user and assistant text only) →
  skip under 2000 characters → newest 120 000 characters → `claude -p
  --setting-sources "" --tools "" --no-session-persistence` with the
  transcript fenced as untrusted data (begin/end markers carry a random
  per-call nonce, so transcript text cannot close the fence; the sweep prompt
  does the same) and the output contract repeated after it → the reply must have exactly six headings in order (or the single
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
line) · plus `claude` CLI and git when the modules that need them are on. A WARN
line lists hook errors of the last 7 days from `state/hook-errors.log`.
