import json
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from lmn.verify_backup import dump_counts, live_counts, verify


class BackupVerificationTest(unittest.TestCase):
    def test_live_counts_respect_d1_compound_select_limit(self):
        expected = {"users": 2, **{f"table_{i}": i for i in range(10)}}
        with closing(sqlite3.connect(":memory:")) as db:
            db.row_factory = sqlite3.Row
            db.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 5)
            for table, count in expected.items():
                db.execute(f'CREATE TABLE "{table}" (id)')
                db.executemany(f'INSERT INTO "{table}" VALUES (?)', [(i,) for i in range(count)])

            def execute(command, **_kwargs):
                rows = [dict(row) for row in db.execute(command[-1])]
                response = json.dumps([{"success": True, "results": rows}])
                return subprocess.CompletedProcess(command, 0, stdout=response)

            with patch.dict("os.environ", {"WRANGLER": "wrangler", "DB": "test"}):
                with patch("lmn.verify_backup.subprocess.run", side_effect=execute):
                    self.assertEqual(live_counts(), expected)

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
