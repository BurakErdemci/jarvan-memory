# Agent error patterns

How AI coding agents fail, written as general rules. Each entry: the rule,
why the failure happens, and a concrete check. Entries marked **[memory]**
are about notes, records and recall; they are the reason for most of this
project's gates.

Consider copying the titles into your vault (for example a note
`topics/Agent_Error_Patterns` with a `READ FIRST` trigger) so they are in
front of the agent at session start.

## 1. Gaps get filled with plausible inventions, causes most of all [memory]

**Rule.** Leave an unknown blank, or write only "X happened". Write "X happened
because Y" only with evidence for Y. Diagnoses and classifications ("this is a
false positive") are claims too.

**Why.** A model fills an unknown with something plausible rather than
leaving a gap. An invented cause is the worst case: it is consistent, nothing
contradicts it, so it feels verified, and it spreads into other notes.

**Check.** Before writing a time, take it from the clock. Before writing a
cause, reproduce the behaviour once. Before classifying a group of events,
test each one. Search your draft for "because", "due to", "so" and confirm
each has a measured basis.

## 2. A silent failure looks like a silent "nothing to report" [memory]

**Rule.** For every component whose silence means something (a hook that does
not block, a search with no hits, a filter that passes), define when it must
speak, and test that case.

**Why.** A crash that exits 0 with empty output is indistinguishable from a
deliberate "nothing here", and the silence invites an explanation (see 1). A
search that cannot match some words reads as "no relevant note".

**Check.** Run the component for real on an input that must produce output.
Test recall against the vocabulary the notes actually use, not hand-picked
strings. Build text meant for a model with quoted heredocs or files, not
inside double-quoted shell strings.

## 3. "It works" has three layers

**Rule.** Say which layer you verified: (1) it runs, (2) its output reaches the
other side (accepted, injected), (3) the other side acts on it, shown by a
trace on disk.

**Why.** Reports default to layer 1, and exit code 0 with empty output counts
as success. Tests can stay green while the live path never reaches the
changed line. A working fallback can hide a broken primary.

**Check.** Drive the real entry point end to end and inspect the artifact the
far side produced. Confirm the live flow reaches the changed code (a log line
on the real path).

## 4. An error message is not a capability list

**Rule.** Do not record "X is unsupported" from one error text or a `--help`
page. Record absence as "not observed", with the evidence.

**Why.** An error explains that one failure; it does not enumerate what is
supported.

**Check.** Before hard-coding a negative, try the supported-looking case
directly.

## 5. Delegated work fails most often in the brief

**Rule.** After writing a task for another agent, reread it from the worker's
seat: can it reach every file mentioned, is anything asked that it is not
allowed to do, does the task invite a known failure of that tool? Quote
"before" code from real tool output, never from memory. Ask the worker to
derive complete lists instead of handing it one.

**Why.** Workers behave correctly on tasks that were impossible or wrong.
Facts written from memory are adopted as truth. A list supplied by the
author becomes the worker's blind spot.

**Check.** List each referenced path from the worker's environment. Diff
quoted code against the file. Search for every user of the thing being
changed. Read the worker's actual output, not only its summary.

## 6. Metadata describes the container, not the work

**Rule.** Before saying when a project started or what a repository is, read
its history and file tree, not its creation date, stars or last-push time.

**Why.** Those fields report events of the container (created late, renamed,
a later maintenance commit). The value is right; the meaning loaded onto it
is wrong.

**Check.** Read the first commits and the messages; separate feature work
from maintenance.

## 7. The instrument measures a neighbouring axis

**Rule.** When a check goes red or green, first ask whether it measures the
target or something next to it. Run a known-answer control, and for
restrictions a must-fail control: break the thing on purpose. If the result
does not change, the instrument is not connected.

**Why.** The tool runs and returns 0 while measuring the wrong thing: a fixed
value assumed unique, a process name that never appears, a stale working
directory, a pipe that replaced the exit code, an empty variable read as
zero, "latest N items" read as "all items", a fetcher that sees only the
initial HTML of a script-rendered page. This gives both false greens and
false reds.

**Check.** Known-answer baseline first. Verify the denominator as well as the
numerator. Compare with a fact you already hold; absurd output is the tell.
Check exit codes without a pipe. Judge liveness by progress markers or
external traces, not a process list.

## 8. Written records diverge [memory]

**8a. Duplicated rules.** A rule lives in one place; other places point to it.
Copies drift, and the copy that loads automatically is often the stale one.
*Check:* search all instruction files for the same rule or number and compare;
compare stated counts with the real state.

**8b. Numbers moved between records.** Do not carry a number or claim from one
record to another without re-checking it at the source; write the command
that produced it next to it. A "not re-verified" stamp is an honesty note,
not a check: the next reader takes the number and ignores the stamp. Records
also claim actions that never happened or were undone. *Check:* re-run the
producing command and diff with the written value; verify actions by their
trace on disk, not by the log's description.

## 9. A gate that covers only one branch

**Rule.** When adding a gate or a fix, count how many paths can trigger the
problem and how many the gate covers. A fix closes a class, not the example
you were shown.

**Why.** The existence of a gate is read as "protected". Its scope is taken
from the single example seen; sibling paths stay open. A noisy source can
hide a second one until the first is fixed. When a refusal offers options of
unequal cost, the cheap one gets chosen.

**Check.** After the fix, search for the same call or pattern across the
repository. Feed the gate boundary inputs from every branch. Make sure a
"once per session" gate does not leave the rest of the session uncovered.

## 10. Verification from the same root yields no information [memory]

**Rule.** Ask whether a check shares a source with what it checks. A session
rereading its own notes, the same review run again, a summary treated as
fact, two implementations that agree, a sub-agent's finding: none of these is
independent. Use another source, tool or fresh reader, and recount claims
yourself.

**Why.** An author reads what they remember, not what is missing. A summary is
written by an agent that can be wrong. Two parties sharing a flawed
definition agree wrongly.

**Check.** Cross-check distilled records against the raw source. Reproduce a
delegated finding yourself (a search, a count) before acting on it.

## 11. The closing step is skipped because the result looks good

**Rule.** A round of fixes is closed only when a verification round has
covered those fixes. The closing criterion is "no unreviewed changes", not
"no open findings". Archive evidence before deleting working areas.

**Why.** Green tests chosen by the fixer share the fixer's blind spot. A
closing note ("done", "zero blockers") does not say whether the review ran,
so the skip is invisible. Deleting before archiving loses the evidence for
good.

**Check.** Record the reviewed revision in the closing note and compare it
with the current one; list changes after the last review.

## 12. Using it yourself is weak evidence

**Rule.** Call a tool sound after an attempt to break it, not after time in
use. Feed guards truncated, empty, malformed and unreadable input.

**Why.** Daily use supplies correct input, so it exercises the happy path.
Defects cluster in retry, error and second-pass paths. A fail-open guard looks
perfect on valid input. Cleanup code that deletes things is itself a defect
source.

**Check.** Give each guard bad input and see what it does. Call cleanup from
inside the thing it cleans up. Keep reviewing while rounds still find new
problems.

## 13. A written rule is not applied at the moment of action [memory]

**Rule.** Put a rule where it is applied: in the command that writes, the
first step of a procedure, the line of a brief. Where a mistake is destructive
or repeated, add a gate or a hook, not a reminder.

**Why.** At action time only what is in the immediate context carries over. A
rule stored in another section, another file or yesterday's note is not
applied. A tool launched without an explicit setting silently uses a default.

**Check.** Before a risky or repeated action, search the notes for the verb or
tool and read the hits. Pass configuration explicitly (model, flags) and check
it. Make destructive commands refuse unless their precondition holds.

## Rules for memory, in short

- Write the command next to every number; re-check at the source when moving it.
- Keep one canonical copy of each rule.
- Never state a cause without evidence.
- Test recall against the vocabulary the notes really use.
- Check summaries against the raw source.
- Do not trust a "verified" or "closed" stamp without the trace it claims.
