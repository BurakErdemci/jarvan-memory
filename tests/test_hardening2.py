"""Regression tests for the second independent memory-system audit."""
import inspect
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import FakeHome
from jarvan_memory import cli, hooks, installer, jobs, search, util, vault as V


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.h = FakeHome()
        self.env = mock.patch.dict(os.environ, self.h.env)
        self.env.start()
        self.cfg = {"vault": str(self.h.vault), "mem_cmd": "mem", "modules": []}
        installer.build_vault(self.cfg, {})
        util.save_config(self.cfg)

    def tearDown(self):
        self.env.stop()
        self.h.cleanup()

    def install(self):
        with mock.patch.object(installer, "find_python", return_value=sys.executable), \
                mock.patch.object(util, "out"):
            return installer.main(["--vault", str(self.h.vault), "--modules", "none",
                                   "--no-doctor"])

    def bash(self, command, cwd=None):
        return {"tool_name": "Bash", "cwd": str(cwd or self.h.work),
                "tool_input": {"command": command}}

    def session(self, sid="audit-session"):
        payload = {"session_id": sid, "cwd": str(self.h.work)}
        sess = hooks.Session(payload)
        sess.load()
        sess.data["prompts"] = hooks.MIN_PROMPTS_FOR_LINE
        sess.save()
        return payload, sess

    def test_install_rejects_every_config_subdirectory(self):
        for target in (self.h.claude, self.h.app, self.h.app / "notes",
                       self.h.claude / "other-notes"):
            with self.subTest(target=target):
                self.assertIsNotNone(installer.unsafe_vault_reason(target))

    def test_uninstall_keeps_legacy_vault_nested_in_runtime(self):
        nested = self.h.app / "runtime" / "legacy-vault"
        nested.mkdir(parents=True)
        note = nested / "valuable.md"
        note.write_bytes(b"irreplaceable")
        self.cfg["vault"] = str(nested)
        util.save_config(self.cfg)
        (self.h.app / "runtime" / "run.py").write_text("runtime", encoding="utf-8")
        with mock.patch.object(util, "out") as out:
            self.assertEqual(installer.uninstall(), 0)
        self.assertEqual(note.read_bytes(), b"irreplaceable")
        self.assertFalse((self.h.app / "runtime" / "run.py").exists())
        self.assertFalse(util.config_path().exists())
        self.assertIn("kept", str(out.call_args))

    def test_uninstall_preserves_foreign_command_mentioning_our_shim(self):
        self.install()
        foreign = {"type": "command", "command": "echo " + installer.hook_command("stop")}
        data = installer.read_settings()
        data["hooks"]["Stop"][0]["hooks"].append(foreign)
        util.write_text(installer.settings_path(), json.dumps(data))
        with mock.patch.object(util, "out"):
            installer.uninstall()
        left = installer.read_settings()
        self.assertIn(foreign, left["hooks"]["Stop"][0]["hooks"])

    def test_uninstall_keeps_even_an_empty_vault_at_an_owned_directory(self):
        for name in ("bin", "runtime", "state", ""):
            nested = self.h.app / name
            nested.mkdir(parents=True, exist_ok=True)
            self.cfg["vault"] = str(nested)
            util.save_config(self.cfg)
            with self.subTest(name=name), mock.patch.object(util, "out"):
                self.assertEqual(installer.uninstall(), 0)
                self.assertTrue(nested.is_dir())

    def test_install_records_exact_hook_commands(self):
        self.install()
        record = util.load_config()["installed"]
        expected = [installer.hook_command(name) for _, _, name, _ in installer.HOOKS]
        self.assertEqual(record["hook_commands"], expected)

    def test_failed_install_restores_existing_vault_exactly(self):
        # Start with an existing folder, rather than the prepared skeleton.
        self.h.vault = self.h.home / "existing"
        self.h.vault.mkdir()
        keep = self.h.vault / "mine.md"
        keep.write_bytes(b"original bytes")
        before = {p.relative_to(self.h.vault): p.read_bytes()
                  for p in self.h.vault.rglob("*") if p.is_file()}
        with mock.patch.object(installer, "install_claude_md", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.install()
        after = {p.relative_to(self.h.vault): p.read_bytes()
                 for p in self.h.vault.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(list(self.h.vault.iterdir()), [keep])

    def test_failed_skeleton_creation_removes_partial_new_files(self):
        self.h.vault = self.h.home / "partial"
        self.h.vault.mkdir()
        original = util.write_text

        def fail(path, text):
            original(path, text)
            if Path(path).parent == self.h.vault:
                raise OSError("partial template write")

        with mock.patch.object(util, "write_text", side_effect=fail):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(list(self.h.vault.iterdir()), [])

    def test_atomic_template_failure_keeps_existing_vault_free_of_scratch(self):
        self.h.vault = self.h.home / "atomic-failure"
        self.h.vault.mkdir()
        keep = self.h.vault / "mine.md"
        keep.write_bytes(b"existing")
        original = os.replace

        def replace(src, dst):
            if Path(dst).parent == self.h.vault:
                raise OSError("atomic replacement denied")
            return original(src, dst)

        with mock.patch.object(os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(list(self.h.vault.iterdir()), [keep])
        self.assertEqual(keep.read_bytes(), b"existing")

    def test_guard_expands_environment_and_honours_subshell_cwd(self):
        stamp = "2026-11-11 10:00"
        with mock.patch.dict(os.environ, {"AUDIT_NOTES": str(self.h.vault)}):
            for prefix in ("$HOME/vault", "${HOME}/vault", "~/vault", "$USERPROFILE/vault",
                           "$AUDIT_NOTES", "${AUDIT_NOTES}"):
                command = f'echo "{stamp}" >> "{prefix}/worklog/x.md"'
                with self.subTest(prefix=prefix):
                    self.assertIsNotNone(hooks.guard_reason(self.bash(command), self.cfg), command)

    def test_guard_restores_parent_cwd_after_a_subshell(self):
        stamp = "2026-11-11 10:00"
        outside = self.h.work.as_posix()
        inside = self.h.vault.as_posix()
        command = f'(cd "{inside}" && echo "{stamp}" > topics/x.md); echo "{stamp}" > worklog/x.md'
        self.assertIsNone(hooks.guard_reason(self.bash(command), self.cfg))
        command = f'(cd "{outside}" && echo "{stamp}" > worklog/x.md); echo "{stamp}" > worklog/x.md'
        self.assertIsNotNone(hooks.guard_reason(self.bash(command, self.h.vault), self.cfg))

    def test_guard_finds_copy_comment_and_privileged_tee(self):
        target = (self.h.vault / "worklog" / "x.md").as_posix()
        for command in (f'cp source "{target}" # 2026-11-11 10:00',
                        f'echo "2026-11-11 10:00" | sudo tee -a "{target}"',
                        f'echo "2026-11-11 10:00" | sudo tee "{target}"'):
            with self.subTest(command=command):
                self.assertIsNotNone(hooks.guard_reason(self.bash(command), self.cfg), command)

    def test_stop_gate_distinguishes_execution_from_quoted_arguments(self):
        for command in ('echo "mem log example"', "grep 'mem verify' readme.md",
                        'git commit -m "run mem log later"', 'echo "a; mem verify x"'):
            self.assertFalse(hooks.touches_vault(self.bash(command), self.cfg), command)
        launcher = (self.h.app / "bin" / "mem").as_posix()
        for command in ('mem log "actual write" --done', 'echo ok && mem verify claim',
                        'false || mem log done', 'true; mem log done',
                        'echo evidence | mem verify claim', f'"{launcher}" log done'):
            self.assertTrue(hooks.touches_vault(self.bash(command), self.cfg), command)

    def test_session_end_with_held_lock_is_fast_and_logs_once(self):
        payload, _ = self.session()
        held = util.FileLock(util.state_dir() / "vault.lock")
        self.assertTrue(held.acquire())
        started = time.monotonic()
        try:
            hooks.session_end(payload)
        finally:
            held.release()
        self.assertLess(time.monotonic() - started, 4)
        errors = util.read_text(hooks.hook_errors_log())
        self.assertEqual(errors.count("TimeoutError"), 1)
        self.assertEqual(list((self.h.vault / V.WORKLOG).glob("*.md")), [])

    def test_session_end_logs_append_and_state_write_errors(self):
        for failure in ("append", "state"):
            payload, _ = self.session("error-" + failure)
            if failure == "append":
                patch = mock.patch.object(V, "append_worklog", side_effect=OSError("append denied"))
            else:
                original = util.write_text

                def write(path, text):
                    if Path(path).name == "miss_streak":
                        raise OSError("state denied")
                    return original(path, text)

                patch = mock.patch.object(util, "write_text", side_effect=write)
            with patch:
                hooks.session_end(payload)
            self.assertIn(failure + " denied", util.read_text(hooks.hook_errors_log()))

    def test_worklog_append_requires_the_vault_lock(self):
        with mock.patch.object(util.FileLock, "acquire", return_value=False):
            with self.assertRaises(TimeoutError):
                V.append_worklog("agent", "audit", "must not be written")
        self.assertEqual(list((self.h.vault / V.WORKLOG).glob("*.md")), [])

    def test_cli_lock_default_is_bounded_and_longer_than_hook_wait(self):
        timeout = inspect.signature(util.vault_lock).parameters["timeout"].default
        self.assertGreater(timeout, 2)
        self.assertLessEqual(timeout, 30)

    def test_both_hook_searches_supply_a_time_budget(self):
        with mock.patch.object(search, "search", return_value=[]) as query:
            hooks.route("alpha beta gamma delta", self.cfg)
            self.assertGreater(query.call_count, 0)
            self.assertGreater(query.call_args.kwargs["budget"], 0)
            self.assertLessEqual(query.call_args.kwargs["budget"], 5)
            query.reset_mock()
            hooks._recall_view("alpha beta gamma delta", self.cfg, ())
            self.assertGreater(query.call_count, 0)
            self.assertGreater(query.call_args.kwargs["budget"], 0)
            self.assertLessEqual(query.call_args.kwargs["budget"], 5)

    def test_large_file_defers_without_partial_rows_then_cli_indexes_it(self):
        note = self.h.vault / "topics" / "Large.md"
        note.write_text("# Large\n\n" + "alpha beta gamma delta\n" * 60000, encoding="utf-8")
        start = time.monotonic()
        con = search.update_index(self.h.vault, self.cfg, budget=0.02)
        try:
            self.assertFalse(search.is_complete(con))
            self.assertEqual(con.execute("SELECT count(*) FROM files WHERE path='topics/Large.md'")
                             .fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT count(*) FROM sections WHERE path='topics/Large.md'")
                             .fetchone()[0], 0)
        finally:
            con.close()
        self.assertLess(time.monotonic() - start, 1)
        con = search.update_index(self.h.vault, self.cfg)
        self.assertTrue(search.is_complete(con))
        self.assertEqual(con.execute("SELECT count(*) FROM files WHERE path='topics/Large.md'")
                         .fetchone()[0], 1)
        con.close()

    def test_fallback_matches_the_same_turkish_stems_as_fts(self):
        note = self.h.vault / "topics" / "Search.md"
        note.write_text("# Search\n\nnot yazma kurali\n", encoding="utf-8")
        cfg = dict(self.cfg, stemmer="tr")
        with mock.patch.object(search, "fts5_available", return_value=False):
            result = search.search("notlarimizda", root=self.h.vault, cfg=cfg)
        self.assertTrue(any(r["path"] == "topics/Search.md" for r in result))

    def test_invalid_names_and_slugs_are_rejected(self):
        for name in ("x" * 121, "bad[[name", "bad]]name", "bad#name", "bad|name"):
            with self.subTest(name=name), self.assertRaises(V.MemError):
                V.note_new("topics", name, force=True)
            with self.subTest(slug=name), self.assertRaises(V.MemError):
                V.infer("claim", "Claim", scope="project", slug=name)
            with self.subTest(handoff=name), self.assertRaises(V.MemError):
                V.handoff_open("Handoff", slug=name)

    def test_index_add_requires_an_existing_note(self):
        with self.assertRaises(V.MemError):
            V.add_index_line("topics/DoesNotExist", "missing")

    def test_file_parent_is_a_clean_cli_error(self):
        (self.h.vault / "topics" / "file-parent").write_bytes(b"keep")
        with mock.patch.object(util, "err") as err:
            self.assertEqual(cli.main(["note", "new", "topics/file-parent", "child", "--force"]), 1)
        self.assertIn("mem:", err.call_args[0][0])

    def test_promote_heading_is_a_whole_case_insensitive_match(self):
        note = self.h.vault / "topics" / "Heading.md"
        note.write_text("# Heading\n\n## Table\n\ntext\n", encoding="utf-8")
        self.assertFalse(V.has_heading(note, "ab"))
        self.assertFalse(V.has_heading(note, "Tab"))
        self.assertTrue(V.has_heading(note, " table "))

    def test_corrupt_config_reports_a_mem_error_without_a_traceback(self):
        util.config_path().write_text("{bad", encoding="utf-8")
        with mock.patch.object(util, "err") as err:
            self.assertEqual(cli.main(["status"]), 1)
        self.assertIn("mem: invalid JSON", err.call_args[0][0])

    def test_verified_claim_can_be_reverified_with_a_new_date(self):
        V.infer("claim", "A measured claim", scope="project", slug="refresh")
        path = V.verify("refresh", "Measured against an independent real fixture")
        util.update_frontmatter(path, verified="2020-01-01 00:00")
        V.verify("refresh", "Measured again against a fresh independent fixture")
        meta, _ = util.parse_frontmatter(util.read_text(path))
        self.assertEqual(meta["verified"], util.stamp())

    def test_summary_repeated_session_calls_model_and_appends_only_once(self):
        transcript = self.h.root / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "user", "message": {
            "content": "A measured decision. " * 200}}), encoding="utf-8")
        job = {"payload": {"session_id": "repeat", "transcript_path": str(transcript)}}
        valid = "\n".join("## " + h + "\n- measured result" for h in jobs.SUMMARY_HEADINGS)
        with mock.patch.object(jobs, "run_claude", return_value=(True, valid)) as model:
            jobs.run_summary(self.cfg, job)
            jobs.run_summary(self.cfg, job)
        self.assertEqual(model.call_count, 1)
        daily = self.h.vault / V.DAILY / (util.today() + ".md")
        self.assertEqual(util.read_text(daily).count("\n## Session "), 1)

    @unittest.skipUnless(os.name == "nt", "Windows command launcher")
    def test_cmd_launcher_handles_unicode_paths_and_restores_codepage(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.h.home / "café")}), \
                mock.patch.object(util, "out"):
            self.install()
            launcher = util.app_dir() / "bin" / "mem.cmd"
            for codepage in (850, 1252, 65001):
                driver = self.h.root / "driver.cmd"
                command = (f'@echo off\r\nchcp {codepage}>nul\r\n'
                           f'call "{launcher}" --version\r\n'
                           'set "RESULT=%errorlevel%"\r\nchcp\r\nexit /b %RESULT%\r\n')
                encoding = "utf-8" if codepage == 65001 else f"cp{codepage}"
                driver.write_bytes(command.encode(encoding))
                # Code pages belong to consoles. Concurrent suite copies must
                # not change one another's decoding while reading a batch file.
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = subprocess.SW_HIDE
                result = subprocess.run(["cmd", "/d", "/c", str(driver)], capture_output=True,
                                        timeout=20, startupinfo=startup,
                                        creationflags=subprocess.CREATE_NEW_CONSOLE)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(b"jarvan-memory", result.stdout)
                self.assertIn(str(codepage).encode(), result.stdout.splitlines()[-1])
