"""Single entry point for hooks, the `mem` CLI and background jobs.

    python run.py hook <event>     (stdin: Claude Code hook payload)
    python run.py cli <args...>    (the `mem` command)
    python run.py job <args...>    (detached background work)
"""
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    kind, rest = sys.argv[1], sys.argv[2:]
    if kind == "hook":
        from jarvan_memory import hooks
        return hooks.main(rest[0] if rest else "")
    if kind == "cli":
        from jarvan_memory import cli
        return cli.main(rest)
    if kind == "job":
        from jarvan_memory import jobs
        return jobs.main(rest)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
