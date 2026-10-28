import json
import os
import threading

from tests.helpers import TempEnvTestCase

from boring_meter import config
from boring_meter.errors import BMError
from boring_meter.paths import validate_output_path
from boring_meter.store import append_jsonl, atomic_write_json, iter_jsonl, read_json


class ConfigTests(TempEnvTestCase):
    with_fixtures = False

    def test_defaults_when_missing(self):
        self.assertEqual(config.load(self.data), config.defaults())

    def test_round_trip(self):
        values = config.defaults()
        values["thresholds.repeated_read_count"] = 7
        config.save(values, self.data)
        self.assertEqual(config.load(self.data)["thresholds.repeated_read_count"], 7)
        stored = json.loads(config.config_path(self.data).read_text())
        self.assertEqual(stored["values"], {"thresholds.repeated_read_count": 7})

    def test_parse_values(self):
        self.assertIs(config.parse_cli_value("pricing.enabled", "off"), False)
        self.assertEqual(config.parse_cli_value("report.default_days", "14"), 14)
        self.assertEqual(config.parse_cli_value("privacy.excluded_projects", "/a, /b"), ["/a", "/b"])
        self.assertEqual(config.parse_cli_value("privacy.excluded_projects", '["/a"]'), ["/a"])
        self.assertEqual(config.parse_cli_value("logging.level", "debug"), "debug")

    def test_invalid_values(self):
        for key, value in [("pricing.enabled", "maybe"), ("report.default_days", "0"), ("report.default_days", "x"),
                           ("logging.level", "loud"), ("time.timezone", "Nowhere/City"), ("no.such.key", "1")]:
            with self.assertRaises(BMError, msg=key):
                config.parse_cli_value(key, value)

    def test_invalid_file(self):
        path = config.config_path(self.data)
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        with self.assertRaises(BMError) as ctx:
            config.load(self.data)
        self.assertEqual(ctx.exception.code, "CORRUPTED_RECORD")
        path.write_text(json.dumps({"config_version": 1, "values": {"report.default_days": -3, "bogus": 1}}))
        with self.assertRaises(BMError) as ctx:
            config.load(self.data)
        self.assertEqual(ctx.exception.code, "INVALID_CONFIG")
        self.assertIn("bogus", ctx.exception.message)
        path.write_text(json.dumps({"config_version": 99, "values": {}}))
        with self.assertRaises(BMError):
            config.load(self.data)

    def test_file_permissions_private(self):
        config.save(config.defaults(), self.data)
        if os.name == "posix":
            self.assertEqual(os.stat(config.config_path(self.data)).st_mode & 0o777, 0o600)


class PathTests(TempEnvTestCase):
    with_fixtures = False

    def test_output_path_rules(self):
        target = self.tmp / "report.md"
        self.assertEqual(validate_output_path(str(target)), target)
        target.write_text("existing")
        with self.assertRaises(BMError) as ctx:
            validate_output_path(str(target))
        self.assertEqual(ctx.exception.code, "OUTPUT_EXISTS")
        self.assertEqual(validate_output_path(str(target), force=True), target)
        with self.assertRaises(BMError):
            validate_output_path(str(self.tmp))
        with self.assertRaises(BMError):
            validate_output_path(str(self.tmp / "missing" / "x.md"))
        with self.assertRaises(BMError):
            validate_output_path("")
        with self.assertRaises(BMError):
            validate_output_path(str(self.claude_dir / "x.md"))
        with self.assertRaises(BMError):
            validate_output_path(str(self.tmp / "sub" / ".." / ".." / os.path.basename(str(self.tmp)) / "claude" / "y.md"))


class StoreTests(TempEnvTestCase):
    with_fixtures = False

    def test_iter_jsonl_errors(self):
        path = self.tmp / "x.jsonl"
        path.write_bytes(b'{"a": 1}\n\nnot json\n[1,2]\n{"b": 2}\n{"c": ')
        results = list(iter_jsonl(path))
        kinds = [(n, e) for n, _o, e in results]
        self.assertEqual(kinds, [(1, None), (2, "blank"), (3, "malformed"), (4, "malformed"), (5, None), (6, "truncated")])

    def test_atomic_write_leaves_no_temp_files(self):
        path = self.tmp / "state" / "s.json"
        atomic_write_json(path, {"x": 1})
        atomic_write_json(path, {"x": 2})
        self.assertEqual(read_json(path), {"x": 2})
        self.assertEqual([p.name for p in path.parent.iterdir()], ["s.json"])

    def test_concurrent_appends_threads(self):
        path = self.tmp / "events.jsonl"

        def worker(n):
            for i in range(25):
                append_jsonl(path, {"worker": n, "i": i, "pad": "x" * 200})

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rows = [o for _n, o, e in iter_jsonl(path) if e is None]
        self.assertEqual(len(rows), 200)

    def test_stale_lock_recovered(self):
        import time as _t
        from boring_meter.store import file_lock

        target = self.tmp / "t.json"
        lock = self.tmp / "t.json.lock"
        lock.write_text("123 0")
        old = _t.time() - 3600
        os.utime(lock, (old, old))
        with file_lock(target, timeout=1):
            pass
        self.assertFalse(lock.exists())

    def test_live_lock_times_out(self):
        from boring_meter.store import file_lock

        target = self.tmp / "t.json"
        with file_lock(target):
            with self.assertRaises(BMError) as ctx:
                with file_lock(target, timeout=0.2):
                    pass
        self.assertEqual(ctx.exception.code, "LOCK_TIMEOUT")
