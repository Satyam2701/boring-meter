"""Shared test helpers. Every test runs against temporary directories only."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.build import build  # noqa: E402


class TempEnvTestCase(unittest.TestCase):
    """Points CLAUDE_CONFIG_DIR and BORING_METER_DATA_DIR at fresh temporary folders."""

    with_fixtures = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bm-test-"))
        self.claude_dir = self.tmp / "claude"
        self.claude_dir.mkdir()
        self.data = self.tmp / "data"
        if self.with_fixtures:
            build(self.claude_dir)
        self._env = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", "BORING_METER_DATA_DIR")}
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.claude_dir)
        os.environ["BORING_METER_DATA_DIR"] = str(self.data)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self, **overrides):
        from boring_meter import config

        values = config.defaults()
        for key, value in overrides.items():
            values[key.replace("__", ".")] = value
        return values

    def dataset(self, **overrides):
        from boring_meter import adapters

        return adapters.load_dataset(self.cfg(**overrides), self.data)
