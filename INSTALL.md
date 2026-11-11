# Installing jarvan-memory (instructions for the installing agent)

You are a Claude Code agent and the user asked you to install this repository.
Follow these steps in order. **Talk to the user in their language** (the
language they wrote to you in) throughout; this file is in English only so
every agent can read it.

The install is done when `mem doctor` prints **N/N checks passing**. Do not
report success before you have seen that line yourself.

## 0. What you are installing (tell the user in two or three sentences)

A memory folder ("vault") of plain Markdown notes, plus Claude Code hooks that
show the relevant part of it at the start of each session, suggest notes when
a prompt clearly matches one, and ask once before a long session ends without
writing anything down. A command, `mem`, is the only writer: it stamps all
dates and keeps the notes in shape. Nothing leaves the machine; no API key,
no network service, no pip packages.

## 1. Requirements

**Python 3.9 or newer** (standard library only) and, on Windows, **Git for
Windows** (Claude Code on Windows already requires it; hooks run in Git Bash).

Check Python. Run each and keep the first that prints a version of 3.9+:

```sh
python3 -c "import sys, sqlite3; print(sys.version)"
python  -c "import sys, sqlite3; print(sys.version)"
py -3   -c "import sys, sqlite3; print(sys.version)"     # Windows launcher
```

On Windows, `python3` is often a Microsoft Store alias that prints an install
hint instead of running. It does not count. If none works, install Python:

| OS | Install | Then verify |
|---|---|---|
| Windows | `winget install -e --id Python.Python.3.12` (then open a new terminal) | `py -3 -c "import sys; print(sys.version)"` |
| macOS | `xcode-select --install` (ships Python 3.9), or `brew install python` | `python3 -c "import sys; print(sys.version)"` |
| Debian/Ubuntu | `sudo apt install python3` | same |
| Fedora | `sudo dnf install python3` | same |
| Arch | `sudo pacman -S python` | same |

Ask the user before installing anything system-wide. If `sqlite3` fails to
import, the Python build is incomplete; install the distribution's full
python3 package.

## 2. Get the code

Clone the repository the user pointed you to, anywhere (the installer copies
what it needs into the Claude config folder, so the clone can be deleted
afterwards):

```sh
git clone <repository URL> jarvan-memory
cd jarvan-memory
```

## 3. Interview the user (short)

Ask these, one message, plain words. Offer the default so they can just say "ok".

1. **Name** — what should notes call you?
2. **What you do** — one or two sentences: your work, main projects. (Goes into the profile note.)
3. **Where to keep the vault** — default `~/claude-memory`. Any folder works; it is plain Markdown, so it can be opened with Obsidian or any editor.
4. **Language for the notes** — default: the language you are talking in.
5. **Optional modules** — explain the cost of each and let them pick any, all, or none:
   - `summary` — at the end of each substantial session (over ~2000 characters of conversation), a background `claude -p` call writes a short summary into `daily/`. Uses the user's Claude subscription (no API key), one model call per such session (default model `sonnet`; changeable in config). Summaries are distilled, not verified.
   - `backup` — the vault becomes a git repository and is committed at every session end. Pushes only if the user adds a remote themselves. Needs git.
   - `sweep` — once a week, a cheap model (`haiku`) reads recent worklog/daily entries against unverified claims and **proposes** refutations, each backed by a verbatim quote. It never changes a record. One small model call per week.
   - If the notes will be in Turkish, also offer the Turkish search stemmer (`--stemmer tr`): it matches inflected forms ("notlarımızda" finds "not").

## 4. Run the installer

Use the interpreter you found in step 1:

```sh
python install.py --name "<name>" --about "<what they do>" \
  --vault "<folder>" --language "<language>" --modules "<summary,backup,sweep or none>"
```

Add `--stemmer tr` if chosen. `~` in `--vault` is expanded. The hooks will
use the interpreter that runs `install.py` (any 3.9+ from step 1 is fine);
pass `--python <absolute path>` only to pick a different one. Re-running the
installer is safe: it is idempotent and never overwrites existing notes.

The installer:
- copies the runtime to `<claude config>/jarvan-memory/` (`~/.claude/jarvan-memory/` by default; `CLAUDE_CONFIG_DIR` is respected),
- creates the vault skeleton (existing files are left alone),
- backs up `settings.json` next to itself and merges seven hooks into it, keeping every existing setting and hook,
- appends a marked block to `~/.claude/CLAUDE.md` that points to the vault's contract,
- runs `mem doctor`.

## 5. Read the doctor output

The installer already ran the doctor; its last line must be
`N/N checks passing`. If not, fix and re-run
`"<claude config>/jarvan-memory/bin/mem" doctor`:

| Failing check | Fix |
|---|---|
| python interpreter | Install Python (step 1), then `<new python> <claude config>/jarvan-memory/runtime/run.py cli repair-python` |
| hooks registered | `settings.json` was edited or is invalid JSON; fix the JSON, re-run the installer |
| hooks fire | Run the failing hook command shown, read its error; on Windows make sure Git for Windows is installed |
| vault writable / skeleton | Check the folder path and permissions; re-run the installer |
| no leftover placeholders | A `{{...}}` remained in a vault file (often after translating); replace it with the real value |
| CLAUDE.md pointer | Re-run the installer |
| search works | The Python's sqlite3 is broken; use another interpreter (`--python`) |
| claude CLI | Needed by `summary`/`sweep`; make sure `claude` is on PATH, or drop those modules |
| git backup | Install git, re-run the installer |

`WARN` and `INFO` lines are not failures. "last real hook runs: none yet" is
expected until Claude Code is restarted.

## 6. Localize the user-facing vault files

The templates are English. If the user's language is not English, rewrite the
**prose** of these files in their language:

- `<vault>/AGENT.md` (the contract), `<vault>/profile.md`, `<vault>/INDEX.md`
- `<vault>/templates/*.md`, `<vault>/topics/README.md`, `<vault>/projects/README.md`

Translate all prose **and headings** in these files; no code reads them.
Keep these exactly as they are, in English, because code reads or writes
them: folder names, file names, every path, the `mem ...` commands and flags,
frontmatter keys (`title`, `status`, ...), status values (`open`,
`unverified`, `verified`, `promoted`, `refuted`, `observation`), the
`READ FIRST` marker in INDEX lines, the `[[link]]` syntax, and the
`(SUPERSEDED)` marker. (Handoff and inference notes are generated by `mem`
with English section headings; leave those headings as `mem` writes them.)

Then fill `profile.md` with what the user told you (the installer already put
the name and the "about" line in; add only what they said, short lines, no
guesses). Write files with your file-writing tool rather than shell heredocs:
the prose is full of quotes and apostrophes. Run `mem doctor` again; it must
still print N/N.

## 7. Finish

Tell the user, in their language:
- where the vault is and that it is plain Markdown they can read and edit,
- that the memory starts working in the **next** Claude Code session (restart it),
- the one command worth knowing: `mem search "<question>"`,
- how to remove it: `mem uninstall` (keeps the vault; `--purge-vault --yes` deletes it too).

The full `mem` path is `<claude config>/jarvan-memory/bin/mem` (`mem.cmd` for
cmd/PowerShell). Agents get it from the session-start block; users who want a
short `mem` can add `<claude config>/jarvan-memory/bin` to their PATH.

## Uninstall

`mem uninstall` removes exactly what the installer added: our hook entries
from `settings.json` (restoring the original bytes when nothing else changed),
the marked CLAUDE.md block, the settings backups, and the runtime folder. The
vault is kept unless the user explicitly asks for `--purge-vault --yes`.
