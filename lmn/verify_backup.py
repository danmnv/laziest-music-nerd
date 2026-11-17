"""Compare a D1 SQL export with counts taken immediately before and after export."""
import json
import os
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

TABLES = """
SELECT name FROM sqlite_schema WHERE type='table'
AND name NOT GLOB 'sqlite_*' AND name NOT GLOB '_cf_*' ORDER BY name
"""


def count_query(tables):
    def table_count(name):
        identifier = '"' + name.replace('"', '""') + '"'
        literal = "'" + name.replace("'", "''") + "'"
        return f"SELECT {literal} AS name, COUNT(*) AS n FROM {identifier}"

    return " UNION ALL ".join(table_count(name) for name in sorted(tables))


def live_counts():
    def execute(sql):
        cmd = shlex.split(os.environ["WRANGLER"]) + [
            "d1", "execute", os.environ["DB"], "--remote", "--json", "--command", sql,
        ]
        call = subprocess.run(cmd, check=True, capture_output=True, text=True)
        entries = json.loads(call.stdout)
        if not entries or any(entry.get("success") is not True for entry in entries):
            raise ValueError("D1 query failed")
        return [row for entry in entries for row in entry["results"]]

    tables = [row["name"] for row in execute(TABLES)]
    if "users" not in tables:
        raise ValueError("D1 has no users table")
    return {row["name"]: row["n"] for row in execute(count_query(tables))}


def dump_counts(path):
    with sqlite3.connect(":memory:") as db:
        db.executescript(path.read_text())
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        tables = [name for (name,) in db.execute(TABLES)]
        return dict(db.execute(count_query(tables))) if tables else {}


def verify(before, dumped, after):
    if before.keys() != after.keys():
        raise ValueError("D1 tables changed during export; retry the backup")
    if "users" not in before or dumped.keys() != before.keys():
        raise ValueError("backup table set differs from live D1")
    for name, n in dumped.items():
        low, high = sorted((before[name], after[name]))
        if not low <= n <= high:
            raise ValueError("a backup row count falls outside the range observed during export")


def main():
    try:
        command, *paths = sys.argv[1:]
        if command == "capture":
            Path(paths[0]).write_text(json.dumps(live_counts()))
        elif command == "verify":
            counts, dump = map(Path, paths)
            before = json.loads(counts.read_text())
            after = live_counts()
            verify(before, dump_counts(dump), after)
        else:
            raise ValueError("unknown backup check command")
    except (OSError, sqlite3.Error, subprocess.SubprocessError, ValueError, KeyError):
        # The workflow is public. Do not emit D1 output, SQL or counts.
        sys.exit("::error::Не удалось подтвердить целостность и полноту выгрузки D1")


if __name__ == "__main__":
    main()
