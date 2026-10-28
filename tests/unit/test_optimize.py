import hashlib

from tests.helpers import TempEnvTestCase

from boring_meter import instructions, optimize
from boring_meter.errors import BMError

TEXT = """# Rules
- Always run the full test suite before committing.
- Prefer small functions with clear names everywhere.

## Testing
- Always run the full test suite before committing.
```
- Always run the full test suite before committing.
```
- Short line
- Short line
"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OptimizeTests(TempEnvTestCase):
    with_fixtures = False

    def setUp(self):
        super().setUp()
        self.project = self.tmp / "proj"
        self.project.mkdir()
        self.target = self.project / "CLAUDE.md"
        self.target.write_text(TEXT)

    def proposal(self):
        analysis = instructions.analyze(self.project, include_user=False)
        result = optimize.build(analysis, self.data)
        self.assertEqual(len(result["proposals"]), 1)
        return result["proposals"][0]

    def test_dedupe_keeps_first_and_code_and_short_lines(self):
        new, removed = optimize.dedupe_text(TEXT)
        self.assertEqual(removed, [6])
        self.assertEqual(new.count("Always run the full test suite"), 2)  # first copy and the code block copy
        self.assertEqual(new.count("Short line"), 2)  # below the minimum length, never touched

    def test_proposal_does_not_modify_file(self):
        before = sha(self.target)
        p = self.proposal()
        self.assertIn("\n-- Always run the full test suite before committing.", p["diff"])
        self.assertEqual(sha(self.target), before)

    def test_apply_without_confirmation_leaves_file_unchanged(self):
        before = sha(self.target)
        p = self.proposal()
        with self.assertRaises(BMError) as ctx:
            optimize.apply(self.data, p["proposal_id"], confirmed=False)
        self.assertEqual(ctx.exception.code, "CONFIRMATION_REQUIRED")
        self.assertEqual(sha(self.target), before)

    def test_apply_with_confirmation(self):
        original = self.target.read_text()
        p = self.proposal()
        result = optimize.apply(self.data, p["proposal_id"], confirmed=True)
        self.assertTrue(result["verified"])
        self.assertEqual(self.target.read_text(), optimize.dedupe_text(original)[0])
        backups = list((self.data / "backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original)
        with self.assertRaises(BMError):
            optimize.apply(self.data, p["proposal_id"], confirmed=True)

    def test_stale_proposal_refused(self):
        p = self.proposal()
        self.target.write_text(TEXT + "- user edit after the proposal was made\n")
        before = sha(self.target)
        with self.assertRaises(BMError) as ctx:
            optimize.apply(self.data, p["proposal_id"], confirmed=True)
        self.assertEqual(ctx.exception.code, "PROPOSAL_STALE")
        self.assertEqual(sha(self.target), before)

    def test_save_copy(self):
        p = self.proposal()
        dest = optimize.save_copy(self.data, p["proposal_id"], str(self.tmp / "proposed.md"))
        self.assertEqual(dest.read_text(), optimize.dedupe_text(TEXT)[0])
        with self.assertRaises(BMError):
            optimize.save_copy(self.data, p["proposal_id"], str(self.tmp / "proposed.md"))
        with self.assertRaises(BMError):
            optimize.save_copy(self.data, p["proposal_id"], str(self.target), force=True)

    def test_bad_proposal_ids(self):
        for bad in ("../../etc", "p-../x", "nope"):
            with self.assertRaises(BMError):
                optimize.load(self.data, bad)
