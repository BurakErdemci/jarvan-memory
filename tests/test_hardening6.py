"""Regression tests for fix round 6: the worklog guard names `worklog` as a path
component (including ~ and $HOME spellings), no longer fires on the vault path
alone, and treats only a real exec flag directly after an interpreter as opaque.
Every case runs through the registered PreToolUse hook command in a fake HOME
where `~` is the folder that holds the vault."""
import time
import unittest

from helpers import BASH, FakeHome
from jarvan_memory import hooks

S = "2026-11-16 10:30"

# (name, command template, denied?); {V} is the vault path, {S} a typed timestamp.
CASES = [
    ("deny_absolute_redirect", "echo '{S} x' >> {V}/worklog/a.md", True),
    ("deny_cd_tilde_worklog", "cd ~/vault/worklog && echo '{S}' >> a.md", True),
    ("deny_cp_to_tilde_worklog", "cp x ~/vault/worklog  # {S}", True),
    ("deny_mv_to_tilde_worklog", "mv x ~/vault/worklog  # {S}", True),
    ("deny_pushd_tilde_worklog", "pushd ~/vault/worklog && echo '{S}' >> a.md", True),
    ("deny_tee_home_var", "echo '{S}' | tee -a $HOME/vault/worklog/a.md", True),
    ("deny_redirect_braced_home", "echo '{S}' >> ${{HOME}}/vault/worklog/a.md", True),
    ("deny_bash_lc", "bash -lc \"echo {S} >> {V}/worklog/a.md\"", True),
    ("deny_cmd_c", "cmd /c \"echo {S} >> {V}/worklog/a.md\"", True),
    ("allow_bash_script_path", "bash /scripts/x.sh  # worklog/a.md {S}", False),
    ("allow_python_script_path", "python /home/x.py  # worklog/a.md {S}", False),
    ("allow_bash_errexit", "bash -e deploy.sh  # worklog/a.md {S}", False),
    ("allow_vault_git_log", "cd {V} && git log --since=\"{S}\"", False),
    ("allow_heredoc_in_vault_topics", "cat > {V}/topics/b.md <<EOF\nnote {S}\nEOF", False),
    ("allow_commit_message_word", "git commit -m \"worklog review {S}\"", False),
    ("allow_printf_word", "printf 'meeting {S} worklog review\n' > notes.md", False),
    ("allow_bash_lc_read_only", "bash -lc 'cd {V} && git log --since=\"{S}\"'", False),
]


@unittest.skipUnless(BASH, "bash not found")
class WorklogGuardCasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = FakeHome()
        cls.h.install("--name", "Ada", "--modules", "none", "--no-doctor")

    @classmethod
    def tearDownClass(cls):
        cls.h.cleanup()

    def verdict(self, template):
        command = template.format(S=S, V=self.h.vault.as_posix())
        reply = self.h.hook("pre-tool", {"tool_name": "Bash", "tool_input": {"command": command}})
        return bool(reply) and reply["hookSpecificOutput"]["permissionDecision"] == "deny"


def _case(template, denied):
    def test(self):
        self.assertEqual(self.verdict(template), denied, template)
    return test


for _name, _template, _denied in CASES:
    setattr(WorklogGuardCasesTest, "test_" + _name, _case(_template, _denied))


class OpaqueFlagRegexTest(unittest.TestCase):
    def test_the_exec_flag_is_its_own_token_after_the_interpreter(self):
        for text in ("bash -c 'x'", "sh -ec x", "bash -c'x'", "fish -c x", "python3 -c x",
                     "node -e x", "perl -e x", "ruby -e x", "php -r x", "pwsh -Command x",
                     "powershell -EncodedCommand x", "cmd /c x", "cmd.exe /d /s /c x"):
            with self.subTest(text=text):
                self.assertTrue(hooks._OPAQUE_SHELL_RE.search(text))
        for text in ("bash /scripts/x.sh", "python /home/x.py", "bash -e deploy.sh",
                     "sh -x run.sh", "cmd /home/x", "python -m pytest"):
            with self.subTest(text=text):
                self.assertFalse(hooks._OPAQUE_SHELL_RE.search(text))

    def test_the_guard_trigger_is_linear_on_a_long_line(self):
        command = f"echo {S} worklog/a.md " + "a" * 90000
        started = time.time()
        hooks._names_worklog_path(command)
        hooks._OPAQUE_SHELL_RE.search(command)
        self.assertLess(time.time() - started, 0.5)


if __name__ == "__main__":
    unittest.main()
