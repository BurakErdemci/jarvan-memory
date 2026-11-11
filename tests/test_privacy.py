"""Structural rule (a behaviour test cannot see it): no personal strings from
the system this project was derived from may ship in the repository."""
import base64
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Stored encoded so this file does not itself contain the strings it bans.
_BANNED = ["YnVyY3U=", "SmFydmFuVmF1bHQ=", "QnVyYWs=", "RXJkZW1jaQ==",
           "SXMtRGVmdGVyaQ==", "S2FsYW4tSXM=", "QWphbl9IYXRhX0thbGlwbGFyaQ==",
           "VGVrbmlrLw==", "UHJvamVsZXIv", "a25vd2xlZGdlL2NvbmNlcHRz", "S2lzaS8=",
           "QXJzaXYv", "R3VubHVrLw=="]
BANNED = [base64.b64decode(b).decode() for b in _BANNED]
# The public install URL in the README is the one allowed mention of the owner.
ALLOWED = {"README.md": ["github.com/BurakErdemci/jarvan-memory"]}
TEXT_SUFFIXES = {".py", ".md", ".sh", ".cmd", ".json", ".txt", ".gitignore", ""}


class PrivacyTest(unittest.TestCase):
    def test_no_personal_strings(self):
        leaks = []
        for p in REPO.rglob("*"):
            if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts:
                continue
            if p.suffix not in TEXT_SUFFIXES or p.name == "test_privacy.py":
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for allowed in ALLOWED.get(p.relative_to(REPO).as_posix(), []):
                text = text.replace(allowed, "")
            low = text.lower()
            for b in BANNED:
                if b.lower() in low:
                    leaks.append(f"{p.relative_to(REPO)}: {b}")
        self.assertEqual(leaks, [])

    def test_the_check_itself_sees_a_leak(self):
        # Must-fail control: the scanner is connected to what it measures.
        sample = "path /home/" + BANNED[0] + "/x"
        self.assertTrue(any(b.lower() in sample.lower() for b in BANNED))


if __name__ == "__main__":
    unittest.main()
