import json
import os
import time

from tests.helpers import TempEnvTestCase
from tests.fixtures.build import EXPECTED

from boring_meter import adapters


class TranscriptAdapterTests(TempEnvTestCase):
    def test_counts_dedup_and_errors(self):
        ds = self.dataset()
        real = [r for r in ds.records if not r["synthetic"]]
        self.assertEqual(len(real), EXPECTED["requests"])
        self.assertEqual(ds.duplicates_removed, EXPECTED["duplicates_removed"])
        self.assertEqual(ds.malformed_lines, EXPECTED["malformed_lines"])
        self.assertEqual(ds.truncated_files, EXPECTED["truncated_files"])

    def test_partial_stream_line_is_replaced_by_final_count(self):
        ds = self.dataset()
        rec = next(r for r in ds.records if r["record_id"] == "cc:msg_a1_1:req_a1_1")
        self.assertEqual(rec["output_tokens"], 100)

    def test_missing_value_stays_none_and_zero_stays_zero(self):
        ds = self.dataset()
        missing = next(r for r in ds.records if r["record_id"].startswith("cc:msg_a2_3"))
        self.assertIsNone(missing["output_tokens"])
        self.assertEqual(missing["data_quality"], "partial")
        zero = next(r for r in ds.records if r["record_id"].startswith("cc:msg_a2_4"))
        self.assertEqual(zero["output_tokens"], 0)
        self.assertEqual(zero["data_quality"], "complete")

    def test_synthetic_placeholder_flagged(self):
        ds = self.dataset()
        synthetic = [r for r in ds.records if r["synthetic"]]
        self.assertEqual(len(synthetic), 1)

    def test_timezone_offsets_normalized_to_utc(self):
        ds = self.dataset()
        rec = next(r for r in ds.records if r["record_id"].startswith("cc:msg_a2_1"))
        # 08:00:10+05:30 is 02:30:10 UTC
        self.assertEqual(time.gmtime(rec["ts_epoch"])[3:6], (2, 30, 10))

    def test_cache_split_preserved(self):
        ds = self.dataset()
        rec = next(r for r in ds.records if r["record_id"].startswith("cc:msg_b1_1"))
        self.assertEqual(rec["other_token_metrics"]["cache_creation_1h"], 2000)
        self.assertEqual(rec["other_token_metrics"]["cache_creation_5m"], 0)

    def test_session_signals(self):
        ds = self.dataset()
        a1 = next(s for s in ds.sessions if s["session_id"] == "synthetic-a1")
        reads = a1["reads"]["/synthetic/alpha/src/app.py"]
        self.assertEqual(reads["count"], 4)
        self.assertEqual(reads["max_unchanged"], 4)
        b1 = next(s for s in ds.sessions if s["session_id"] == "synthetic-b1" and s["file"].endswith("synthetic-b1.jsonl"))
        self.assertEqual(b1["full_writes"]["/synthetic/beta/out.md"], 3)
        self.assertEqual(b1["max_tokens_stops"], 1)

    def test_edit_resets_unchanged_read_count(self):
        path = self.claude_dir / "projects" / "-synthetic-edit" / "synthetic-e1.jsonl"
        path.parent.mkdir(parents=True)
        lines = []
        for i, tool in enumerate(["Read", "Read", "Edit", "Read", "Read"]):
            lines.append({"type": "assistant", "sessionId": "synthetic-e1", "timestamp": "2026-10-20T10:0%d:00Z" % i,
                          "message": {"id": "m%d" % i, "model": "claude-opus-5-5", "content": [
                              {"type": "tool_use", "id": "t%d" % i, "name": tool, "input": {"file_path": "/synthetic/x.py"}}],
                              "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0,
                                        "cache_creation_input_tokens": 0}}})
        path.write_text("".join(json.dumps(l) + "\n" for l in lines))
        res = adapters.scan_transcript(path)
        info = res.sessions["synthetic-e1"]["reads"]["/synthetic/x.py"]
        self.assertEqual(info["count"], 4)
        self.assertEqual(info["max_unchanged"], 2)

    def test_non_transcript_and_empty_files_ignored(self):
        ds = self.dataset()
        statuses = {os.path.basename(f["path"]): f["status"] for f in ds.files}
        self.assertEqual(statuses["journal.jsonl"], "not_transcript")
        self.assertEqual(statuses["empty.jsonl"], "ok")

    def test_large_file_skipped(self):
        big = self.claude_dir / "projects" / "-synthetic-big" / "big.jsonl"
        big.parent.mkdir(parents=True)
        big.write_bytes(b"{}\n" * (600 * 1024))  # about 1.8 MB
        ds = self.dataset(sources__max_file_mb=1)
        self.assertTrue(any(p.endswith("big.jsonl") and "larger" in r for p, r in ds.skipped_files))

    def test_symlink_outside_root_not_followed(self):
        outside = self.tmp / "outside.jsonl"
        outside.write_text((self.claude_dir / "projects" / "-synthetic-alpha" / "synthetic-a1.jsonl").read_text())
        link = self.claude_dir / "projects" / "-synthetic-alpha" / "link.jsonl"
        os.symlink(str(outside), str(link))
        ds = self.dataset()
        self.assertTrue(any(p.endswith("link.jsonl") for p, _r in ds.skipped_files))

    def test_cache_reused_and_invalidated(self):
        first = self.dataset()
        cache_files = list((self.data / "cache").glob("transcripts-*.json"))
        self.assertEqual(len(cache_files), 1)
        second = self.dataset()
        self.assertEqual(len(first.records), len(second.records))
        path = self.claude_dir / "projects" / "-synthetic-beta" / "synthetic-b1.jsonl"
        with open(path, "a") as handle:
            handle.write(json.dumps({"type": "assistant", "sessionId": "synthetic-b1", "timestamp": "2026-10-22T13:00:00Z",
                                     "requestId": "req_new", "message": {"id": "msg_new", "model": "claude-opus-5-5",
                                     "content": [], "usage": {"input_tokens": 1, "output_tokens": 1,
                                     "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}}) + "\n")
        third = self.dataset()
        self.assertEqual(len(third.records), len(first.records) + 1)

    def test_corrupt_cache_is_rebuilt(self):
        self.dataset()
        cache_file = next((self.data / "cache").glob("transcripts-*.json"))
        cache_file.write_text("{ not json")
        ds = self.dataset()
        self.assertEqual(len([r for r in ds.records if not r["synthetic"]]), EXPECTED["requests"])

    def test_excluded_projects(self):
        ds = self.dataset(privacy__excluded_projects=["/synthetic/beta"])
        self.assertFalse(any((r["project_id"] or "").startswith("/synthetic/beta") for r in ds.records))

    def test_no_message_content_is_stored(self):
        ds = self.dataset()
        blob = json.dumps(ds.records) + json.dumps(ds.sessions)
        self.assertNotIn("[synthetic prompt]", blob)
        self.assertNotIn("[synthetic]", blob)

    def test_missing_source_reported(self):
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "nowhere")
        ds = self.dataset()
        self.assertEqual(ds.records, [])
        self.assertEqual(ds.sources[0].status, "missing")

    def test_disabled_source(self):
        ds = self.dataset(sources__claude_transcripts=False)
        self.assertEqual(ds.records, [])
        self.assertEqual(ds.sources[0].status, "disabled")


class HookEventTests(TempEnvTestCase):
    with_fixtures = False

    def test_prune_events_respects_retention(self):
        from boring_meter.store import append_jsonl

        path = adapters.events_path(self.data)
        append_jsonl(path, {"schema_version": 1, "file_path": "/x", "ts": "2020-01-01T00:00:00+00:00"})
        append_jsonl(path, {"schema_version": 1, "file_path": "/y", "ts": "2099-01-01T00:00:00+00:00"})
        removed = adapters.prune_events(self.data, 30)
        self.assertEqual(removed, 1)
        events = adapters.load_instruction_events(self.data)
        self.assertEqual([e["file_path"] for e in events], ["/y"])

    def test_retention_zero_keeps_everything(self):
        from boring_meter.store import append_jsonl

        append_jsonl(adapters.events_path(self.data), {"schema_version": 1, "file_path": "/x", "ts": "2020-01-01T00:00:00+00:00"})
        self.assertEqual(adapters.prune_events(self.data, 0), 0)
