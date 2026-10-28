import errno
import json
import os
import threading
from pathlib import Path
from unittest import mock

from tests.helpers import TempEnvTestCase

from boring_meter import config, paths, store
from boring_meter.errors import BMError
from boring_meter.paths import validate_output_path
from boring_meter.store import append_jsonl, atomic_write_json, atomic_write_text, iter_jsonl, read_json


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


class _OSView:
    """Stands in for the os module inside one boring_meter module, with some attributes replaced.

    Patching os.name itself would also switch pathlib to WindowsPath and break it.
    """

    def __init__(self, name, **overrides):
        self.name = name
        self.__dict__.update(overrides)

    def __getattr__(self, attr):
        return getattr(os, attr)


class DataDirTests(TempEnvTestCase):
    """Each platform branch of paths.data_dir, exercised by faking sys.platform and os.name."""

    with_fixtures = False

    def data_dir_for(self, platform, os_name, env):
        keep = {k: v for k, v in os.environ.items() if k not in ("BORING_METER_DATA_DIR", "LOCALAPPDATA", "XDG_DATA_HOME")}
        keep.update(env)
        with mock.patch.dict(os.environ, keep, clear=True), \
                mock.patch.object(paths.sys, "platform", platform), mock.patch.object(paths, "os", _OSView(os_name)):
            return paths.data_dir()

    def test_override_wins_everywhere(self):
        for platform, os_name in (("darwin", "posix"), ("linux", "posix"), ("win32", "nt")):
            got = self.data_dir_for(platform, os_name, {"BORING_METER_DATA_DIR": str(self.tmp / "custom")})
            self.assertEqual(got, self.tmp / "custom")

    def test_macos(self):
        self.assertEqual(self.data_dir_for("darwin", "posix", {}),
                         Path.home() / "Library" / "Application Support" / "boring-meter")

    def test_linux_xdg_and_default(self):
        self.assertEqual(self.data_dir_for("linux", "posix", {"XDG_DATA_HOME": str(self.tmp / "xdg")}),
                         self.tmp / "xdg" / "boring-meter")
        self.assertEqual(self.data_dir_for("linux", "posix", {}), Path.home() / ".local" / "share" / "boring-meter")

    def test_windows_localappdata_and_default(self):
        self.assertEqual(self.data_dir_for("win32", "nt", {"LOCALAPPDATA": str(self.tmp / "local")}),
                         self.tmp / "local" / "boring-meter")
        self.assertEqual(self.data_dir_for("win32", "nt", {}), Path.home() / "AppData" / "Local" / "boring-meter")


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

        errors = []

        def worker(n):
            try:
                for i in range(25):
                    append_jsonl(path, {"worker": n, "i": i, "pad": "x" * 200})
            except Exception as exc:  # surface failures from threads
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        rows = [o for _n, o, e in iter_jsonl(path) if e is None]
        self.assertEqual(len(rows), 200)

    def test_lock_treats_windows_permission_error_as_busy(self):
        from unittest import mock
        from boring_meter import store

        target = self.tmp / "w.json"
        real_open = os.open
        calls = {"n": 0}

        def flaky_open(path, flags, *args):
            if str(path).endswith(".lock") and calls["n"] < 2:
                calls["n"] += 1
                raise PermissionError(13, "Access is denied")
            return real_open(path, flags, *args)

        with mock.patch.object(store, "IS_WINDOWS", True), mock.patch.object(store.os, "open", flaky_open):
            with store.file_lock(target, timeout=2):
                pass
        self.assertEqual(calls["n"], 2)

    def test_lock_permission_error_fatal_off_windows(self):
        from unittest import mock
        from boring_meter import store

        def denied(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        with mock.patch.object(store, "IS_WINDOWS", False), mock.patch.object(store.os, "open", denied):
            with self.assertRaises(BMError) as ctx:
                with store.file_lock(self.tmp / "p.json", timeout=0.2):
                    pass
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

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

    def test_disk_full_during_replace_maps_to_storage_full(self):
        path = self.tmp / "state" / "s.json"
        atomic_write_text(path, "old\n")
        with mock.patch.object(store.os, "replace", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            with self.assertRaises(BMError) as ctx:
                atomic_write_text(path, "new\n")
        self.assertEqual(ctx.exception.code, "STORAGE_FULL")
        self.assertEqual(path.read_text(), "old\n")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["s.json"])

    def test_disk_full_during_write_maps_to_storage_full(self):
        path = self.tmp / "state" / "s.json"
        with mock.patch.object(store.os, "fsync", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            with self.assertRaises(BMError) as ctx:
                atomic_write_text(path, "new\n")
        self.assertEqual(ctx.exception.code, "STORAGE_FULL")
        self.assertEqual(list(path.parent.iterdir()), [])

    def test_appended_lines_end_with_lf_only(self):
        path = self.tmp / "events.jsonl"
        append_jsonl(path, {"a": 1})
        append_jsonl(path, {"b": 2})
        self.assertEqual(path.read_bytes(), b'{"a": 1}\n{"b": 2}\n')

    def test_windows_replace_retries_while_target_is_busy(self):
        busy = PermissionError(errno.EACCES, "Access is denied")
        replace = mock.Mock(side_effect=[busy, busy, None])
        with mock.patch.object(store, "os", _OSView("nt", replace=replace)), mock.patch.object(store.time, "sleep"):
            store._replace("a", "b")
        self.assertEqual(replace.call_count, 3)

    def test_replace_does_not_retry_off_windows(self):
        busy = PermissionError(errno.EACCES, "Permission denied")
        replace = mock.Mock(side_effect=busy)
        with mock.patch.object(store, "os", _OSView("posix", replace=replace)):
            with self.assertRaises(PermissionError):
                store._replace("a", "b")
        self.assertEqual(replace.call_count, 1)
