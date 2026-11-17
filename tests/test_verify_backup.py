import tempfile
import unittest
from pathlib import Path

from lmn.verify_backup import dump_counts, verify


class BackupVerificationTest(unittest.TestCase):
    def test_dump_validation_detects_missing_table_and_partial_row_loss(self):
        live = {"users": 2, "marks": 2}
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "dump.sql"
            users = "CREATE TABLE users(id); INSERT INTO users VALUES (1),(2);"
            marks = "CREATE TABLE marks(id); INSERT INTO marks VALUES (1);"
            for sql in (users, users + marks):
                dump.write_text(sql)
                with self.assertRaises(ValueError):
                    verify(live, dump_counts(dump), live)

            dump.write_text(users + marks + "INSERT INTO marks VALUES (2);")
            verify(live, dump_counts(dump), live)

    def test_growth_and_deletions_are_allowed_within_the_measured_range(self):
        verify({"users": 2, "marks": 4}, {"users": 3, "marks": 3}, {"users": 4, "marks": 2})
        with self.assertRaises(ValueError):
            verify({"users": 2}, {"users": 2}, {"users": 2, "marks": 0})
