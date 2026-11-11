# Design principles

Each principle is here because the opposite was tried and failed. The reason
is written next to it, so a change can argue with the reason instead of the
rule.

## Code writes what the model cannot know

**Timestamps come from the clock, never from the model.** The model has no
clock; asked to write a time, it writes a plausible one. Every date in the
vault is stamped by `mem` or a hook, and the worklog guard refuses typed ones.

**Frontmatter is generated.** Hand-written headers drift: fields get dropped,
formats vary, and later tools that read them break quietly.

## One writer, one source of truth

**`mem` is the only structured writer.** A rule like "keep lines short" or
"say whether work is open" is enforced where the line is written, not
remembered by whoever writes it. Rules that depend on recall do not fire.

**Derived lists are derived every time.** The list of open handoffs is
computed from each note's own `status` on every call. A stored list is a
second copy that drifts, and a drifted index is worse than none: it is read
as current.

**A rule lives in one place.** The contract is in the vault; CLAUDE.md only
points to it. Two copies of a rule diverge, and the copy that loads
automatically is usually the stale one.

## Required beats optional

**Binary declarations instead of optional fields.** "Is work carried over?"
was an optional field and got skipped. `mem log` refuses until you say
`--done` or name a handoff. A free-text field cannot answer it either: people
describe finished work in the "what's left" field.

**A worklog line is a pointer.** At most 200 characters. Session start shows
lines whole; a long line either bloats every session or gets cut, and a cut
line loses its link to the detail.

## Silence must mean something

**Never truncate silently.** A note cut off the session-start block looks
exactly like a note that was never written. Over budget, the block says how
big it is; over a cap, it says how many lines it did not show.

**A dead component must not look like a quiet one.** A hook that crashes
and exits 0 with no output is indistinguishable from one that had nothing to
say. Session start reports a missing interpreter, failed background jobs and
its own exceptions. Doctor probes the real hook commands instead of checking
that files exist.

**Strict gates for suggestions.** A suggestion that is usually irrelevant
trains the reader to ignore all of them. Prompt suggestions and failure
recall stay silent unless one section covers most of the words.

## Gates that ask, not gates that nag

**The stop gate asks once per long stretch and re-arms.** A single-shot gate
went quiet for the rest of a long session that produced findings nobody
recorded. A gate on every short exchange becomes noise people dismiss.

**It never forces content.** The question explicitly allows "nothing durable
happened" (one honest worklog line). A record written only to pass a check
makes the quarantine useless.

**It cannot loop and cannot be burned by a crash.** `stop_hook_active` turns
are never blocked; the block is recorded only after the reply was printed.

**Attribution by the session's own tool calls.** "Did this session write to
memory" is set by this session's PostToolUse events. A vault-wide mtime scan
has no owner: with two sessions open, one session's writes disarm the other's
gate.

## Knowledge has a lifecycle

**Observation vs claim.** Observations are free. A claim is an inference that
would change behaviour; it waits in quarantine until checked.

**Promotion needs fresh verification, not repetition.** Three observations
from the same source are one claim said three times. Verification means a new
measurement, a re-run, a read of the source. A check that shares its root
with the thing checked yields no information.

**The target must exist before promotion.** Otherwise a record can claim to
live in a section that was never written.

**Claims about the user are the user's to confirm** (`scope: person`). There
is no default scope, because a default silently decides who has authority.

**Refuted records are kept.** They are the only thing that stops the same
wrong inference from being made again.

**Superseded decisions are marked, not deleted.** Search downranks
`(SUPERSEDED)` headings, so the newest decision wins without losing the
history.

## Background work is bounded and isolated

**A child model run must not load the user's hooks.** Without
`--setting-sources ""` a summary call would fire this system's own hooks
inside the child. An environment flag is the second layer.

**Everything that spawns has a limit.** Locks with staleness, timeouts that
kill the whole process tree (on Windows `claude` is a `.cmd` shim whose real
work is a grandchild), a weekly interval for the sweep, a minimum size for
summaries.

**A cheap model only proposes.** The sweep may suggest a refutation backed by
a verbatim quote that is checked against what it was shown. It never changes
a record.

## Portability is tested, not assumed

**UTF-8 everywhere, explicitly.** On Windows the default code page cannot
encode most non-English text; a hook that prints one such character can die
mid-output. All hook I/O goes through UTF-8 bytes, and child processes get
`encoding="utf-8"`.

**Paths arrive in several dialects.** Windows payloads mix `C:\`, `C:/` and
`/c/`. Paths are normalized before comparing, and git's own answer is used
for "is this the repo root".

**The interpreter is probed by running it.** The Windows Store `python3`
alias is on PATH, prints a hint and exits 0. Only an interpreter that runs
code and reports its real path is accepted.

## Tests protect promises

Tests drive the real entry points (the installer, the registered hook
command through bash, the `mem` launcher) and check what they leave on disk.
Each test protects one promise a user would notice. Only the paid model is
faked, by a recorder that replays a canned reply. A test that does not turn
red when the code it protects is broken protects nothing, so the gates were
checked by breaking them on purpose.
