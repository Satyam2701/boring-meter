"""Repository-wide writing rule: no em dash characters in any generated text."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EM_DASH = chr(0x2014)
SKIP_DIRS = {".git", "__pycache__", ".claude"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".txt", ".toml", ".cfg", ".sh", ""}


class NoEmDashTests(unittest.TestCase):
    def test_no_em_dash_in_repository(self):
        offenders = []
        for path in ROOT.rglob("*"):
            if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts) or not path.is_file():
                continue
            if path.suffix not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if EM_DASH in line:
                    offenders.append("%s:%d" % (path.relative_to(ROOT), number))
        self.assertEqual(offenders, [], "Em dash found in: %s" % ", ".join(offenders))
