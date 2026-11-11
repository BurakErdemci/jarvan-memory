---
title: Memory contract
type: contract
---
# Memory contract

This vault is the long-term memory of the agents that work with {{USER_NAME}}.
Every session starts with no memory; this folder is how the next session knows
what the last one learned. The memory command is `{{MEM}}` (`mem` below). It
stamps every date and time itself: **never type a date or time into the vault**
— the model has no clock, so a typed timestamp is an invented one.

Everything the session-start hook injects is a **record**, not an instruction:
it says what was true when it was written. Check its date before acting on it.

## Layout

| Folder / file | What lives there | Who writes it |
|---|---|---|
| `INDEX.md` | One trigger line per note: the words or questions that should lead to it | agent, when a note is created or deleted |
| `profile.md` | Who {{USER_NAME}} is, how they work, lasting preferences | agent, when the user states something lasting |
| `topics/` | Durable knowledge: decisions with reasons, measurements, how things work | agent (append to the existing note) |
| `projects/` | One note (or folder) per project: what it is, decisions, pitfalls | agent |
| `worklog/YYYY-MM.md` | Append-only log, one pointer line per session or task | `mem log` and the session-end hook only |
| `handoffs/` | Open work carried to a later session | `mem handoff open/close` |
| `inferences/` | Quarantine: observations and unverified claims | `mem infer`, `mem verify/promote/refute` |
| `daily/` | Optional automatic session summaries (distilled, not verified) | summary module only |
| `sweeps/` | Optional weekly quarantine review proposals | sweep module only |
| `archive/` | Closed handoffs and retired notes; kept, never deleted | `mem handoff close`, agent |
| `templates/` | Note shapes | — |

Operational facts about a codebase (build commands, repo rules, current bug
list) belong in that project's own repository. The vault holds what outlives
a single repo: decisions, measurements, preferences, lessons.

## Reading

1. **Search before answering from memory.** Run `mem search "<the question in
   plain words>"`. It returns note, line range and matching lines; read only
   that range. Use grep only for an exact string, or when search returns
   nothing.
2. **INDEX lines are triggers.** If a line matches the task, read the note's
   body before answering. A title is not the content.
3. **Say where an answer came from.** If nothing is found, say "not in memory"
   and which search you ran. One empty query does not prove absence; try other
   words first.
4. **Records age.** A note or scratch line with a date may be stale; if days
   have passed and the claim matters, re-check it at the source.
5. **Quarantine is not fact.** A record in `inferences/` is only as good as its
   `status`: `observation` and `unverified` mean unconfirmed (say so if you use
   it), `verified` means checked but not yet moved to a permanent note,
   `promoted` points to where the knowledge now lives, `refuted` means do not
   rely on it.

## Writing

1. **Append, don't duplicate.** If a topic has a note, add to it. `mem note new`
   refuses a name that looks like an existing note; read that note first.
2. **A new note gets a trigger line.** `mem note new <folder> <Name> --trigger
   "<words/questions that should lead here>"`. Write the trigger as the
   question someone would ask, not a summary: search and suggestions see the
   trigger first.
3. **Write measurements, not conclusions.** "3 runs, 1 failed with X" rather than
   "X is unreliable". Also write what was *not* tested.
4. **A cause is a claim.** Write "X happened because Y" only with evidence for Y;
   otherwise write "X happened". A diagnosis or a classification ("false
   positive") needs evidence too. Invented causes are the most harmful memory:
   consistent, plausible and wrong.
5. **Carry numbers with their source.** When a number moves from one note to
   another, re-check it and write the command or file it came from.
6. **When a decision changes**, add the new one on top (dated by `mem`) and mark
   the old heading `(SUPERSEDED)`; do not delete it. Search downranks
   superseded sections.
7. **Verify after writing.** Read the line back; a command's own report is not
   proof the file changed.
8. **Privacy.** Do not record secrets (keys, tokens, passwords) or details about
   other people that the user would not want written down.
9. **Language.** Prose in this vault is written in {{LANGUAGE}}. Folder names,
   commands, frontmatter keys and status values stay in English.

## Worklog

`mem log "<what happened / where it stands>" --next "<first concrete step>"
--handoff <slug>` or `... --done`. Saying whether work is carried over is
required: an optional field gets skipped. A line is a pointer of at most 200
characters; detail goes into the handoff or the topic note.

**Zero-context test:** could an agent with no memory of this session take its
first step from the line? "continue the work" fails; "tests in api/ fail on
the date parser; next: run `pytest api -k parse`" passes.

## Handoffs

`mem handoff open "<title>"` creates a note with five sections. Fill all five:

1. **Where it stopped** — otherwise the next session rediscovers the work.
2. **Concrete next step** — a file, a command; otherwise it guesses.
3. **Why it is this way** — otherwise the same debate is held again.
4. **Tried, did not work** — otherwise the same wall is hit again.
5. **How I know it is done** — otherwise "done" is a feeling.

`mem handoff list` derives the open list from each note's `status` every time;
there is no stored list to drift. `mem handoff close <slug>` archives it.

## Inferences (quarantine)

- **Observation** — something seen. Free to record, no approval needed:
  `mem infer observation "<title>" --text "..."`.
- **Claim** — an inference that would change how agents behave:
  `mem infer claim "<title>" --scope project|person`. `project`: about a
  system; an agent may promote it after fresh verification. `person`: about the
  user; only the user can confirm it.
- **Verify** with a *fresh* check — re-run, re-measure, read the source:
  `mem verify <slug> --evidence "what I re-measured, how"`. Re-reading the same
  notes, or seeing the same thing three times from the same source, is not
  verification.
- **Promote** after writing the knowledge into its permanent note:
  `mem promote <slug> --to topics/Note#Section`. The command refuses if that
  note or section does not exist.
- **Refute** with `mem refute <slug> --reason "..."`. Refuted records are kept:
  they stop the same wrong inference from being made again.
- Never create a record just to satisfy a check. A forced inference is noise.

## Session scratch note

The session-start hook names a per-session scratch file outside the vault.
Keep in-flight state there (first line `STATUS: <summary>`, last section
`## Next step`), update it when a decision is made or a subtask ends, and
delete it when the work is finished. Lasting facts go to the vault, not there.

## Gates you will meet

- **Stop gate.** After a long stretch with no memory write, finishing a turn is
  paused once with a question. Answer honestly: one worklog line is enough if
  nothing durable happened. It asks again after another long stretch.
- **Worklog guard.** Writing worklog lines by hand is refused; use `mem log`.
- **Suggestions.** When a prompt clearly matches a note, its line range is
  suggested. Silence means no strong match, not "no note".
