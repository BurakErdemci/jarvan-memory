"""Gate promises, driven through the registered hook commands: the stop gate
blocks a long session with no memory write, re-arms, never loops; the
worklog guard refuses hand-typed timestamps."""
import json
import unittest
import uuid

from helpers import HomeTest

INTERVAL = 10


class StopGateTest(HomeTest):
    def session(self):
        return "g" + uuid.uuid4().hex[:10]

    def prompts(self, sid, n):
        for _ in range(n):
            self.h.hook("user-prompt", {"session_id": sid, "prompt": "ok"})

    def stop(self, sid, active=False):
        return self.h.hook("stop", {"session_id": sid, "stop_hook_active": active})

    def write(self, sid):
        cmd = '"' + str(self.h.app / "bin" / "mem").replace("\\", "/") + '" log "x" --done'
        self.h.hook("post-tool", {"session_id": sid, "tool_name": "Bash",
                                  "tool_input": {"command": cmd}})

    def test_short_session_is_not_blocked(self):
        sid = self.session()
        self.prompts(sid, INTERVAL - 1)
        self.assertIsNone(self.stop(sid))

    def test_long_session_without_write_is_blocked_once_then_rearms(self):
        sid = self.session()
        self.prompts(sid, INTERVAL)
        r = self.stop(sid)
        self.assertEqual(r["decision"], "block")
        self.assertIn("Do NOT invent", r["reason"])
        # The answer to a block is never blocked again (no loop).
        self.assertIsNone(self.stop(sid, active=True))
        # Same stretch: no second question.
        self.prompts(sid, INTERVAL - 1)
        self.assertIsNone(self.stop(sid))
        # Another full stretch without a write: asked again.
        self.prompts(sid, 1)
        r = self.stop(sid)
        self.assertEqual(r["decision"], "block")
        self.assertIn("Asking again", r["reason"])

    def test_memory_write_disarms_for_the_stretch(self):
        sid = self.session()
        self.prompts(sid, INTERVAL)
        self.write(sid)
        self.assertIsNone(self.stop(sid))
        self.prompts(sid, INTERVAL)
        self.assertEqual(self.stop(sid)["decision"], "block")

    def test_reading_memory_does_not_count_as_writing(self):
        sid = self.session()
        self.prompts(sid, INTERVAL)
        cmd = '"' + str(self.h.app / "bin" / "mem").replace("\\", "/") + '" search "deploy"'
        self.h.hook("post-tool", {"session_id": sid, "tool_name": "Bash",
                                  "tool_input": {"command": cmd}})
        self.assertEqual(self.stop(sid)["decision"], "block")

    def test_edit_inside_vault_counts_as_write(self):
        sid = self.session()
        self.prompts(sid, INTERVAL)
        self.h.hook("post-tool", {"session_id": sid, "tool_name": "Edit",
                                  "tool_input": {"file_path": str(self.h.vault / "topics" / "X.md")}})
        self.assertIsNone(self.stop(sid))


class WorklogGuardTest(HomeTest):
    def pre(self, tool, tool_input):
        r = self.h.hook("pre-tool", {"tool_name": tool, "tool_input": tool_input})
        return (r or {}).get("hookSpecificOutput", {}).get("permissionDecision")

    def test_bash_append_with_typed_timestamp_is_denied(self):
        wl = str(self.h.vault / "worklog" / "2026-01.md").replace("\\", "/")
        cmd = f'echo "- 2026-01-05 10:00 · agent · x · did it" >> "{wl}"'
        self.assertEqual(self.pre("Bash", {"command": cmd}), "deny")

    def test_write_tool_on_worklog_is_denied(self):
        self.assertEqual(self.pre("Write", {"file_path": str(self.h.vault / "worklog" / "2026-01.md"),
                                            "content": "x"}), "deny")

    def test_mem_log_and_edits_are_allowed(self):
        mem = '"' + str(self.h.app / "bin" / "mem").replace("\\", "/") + '"'
        self.assertIsNone(self.pre("Bash", {"command": f'{mem} log "built it" --done'}))
        self.assertIsNone(self.pre("Edit", {"file_path": str(self.h.vault / "worklog" / "2026-01.md"),
                                            "old_string": "a", "new_string": "b"}))
        self.assertIsNone(self.pre("Write", {"file_path": str(self.h.vault / "topics" / "A.md"),
                                             "content": "2026-01-05 10:00 measured"}))

    def test_mem_log_refuses_typed_timestamp(self):
        r = self.h.mem("log", "2026-01-05 10:00 shipped", "--done")
        self.assertEqual(r.returncode, 1)
        self.assertIn("timestamp", r.stderr)


class SessionEndTest(HomeTest):
    def test_session_end_writes_a_clock_stamped_line_for_real_sessions(self):
        sid = "e" + uuid.uuid4().hex[:8]
        for _ in range(3):
            self.h.hook("user-prompt", {"session_id": sid, "prompt": "ok"})
        self.h.hook("session-end", {"session_id": sid})
        lines = []
        for p in (self.h.vault / "worklog").glob("*.md"):
            lines += [l for l in p.read_text(encoding="utf-8").splitlines() if " · session · " in l]
        self.assertTrue(any("3 prompts" in l and "memory: not written" in l for l in lines), lines)

    def test_tiny_session_leaves_no_line(self):
        sid = "t" + uuid.uuid4().hex[:8]
        self.h.hook("user-prompt", {"session_id": sid, "prompt": "hi"})
        self.h.hook("session-end", {"session_id": sid})
        text = "".join(p.read_text(encoding="utf-8") for p in (self.h.vault / "worklog").glob("*.md"))
        self.assertNotIn(" · 1 prompts", text)


if __name__ == "__main__":
    unittest.main()
