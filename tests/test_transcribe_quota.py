import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lmn import gemini, transcribe, transcribe_quota as quota


class ArchiveQuotaTest(unittest.TestCase):
    morning = datetime(2026, 11, 18, 9, tzinfo=timezone.utc)
    late = datetime(2026, 11, 19, 7, 7, tzinfo=timezone.utc)
    reset = datetime(2026, 11, 19, 8, tzinfo=timezone.utc)
    limits = {"flash-lite": 24, "flash": 8, "hydrogen": 4}
    extra_limits = {"flash-lite": 8, "hydrogen": 1}

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / quota.FILENAME

    def claim(self, slot, owner, now):
        quota.claim(self.path, slot, owner, 360, self.limits, self.extra_limits, now)

    def test_completed_and_interrupted_runs_share_the_same_pacific_day(self):
        self.claim("main", "1", self.morning)
        morning = self.path.read_text()
        # A rerun after a crash cannot replace the first reservation.
        self.claim("main", "2", self.morning)
        self.assertEqual(self.path.read_text(), morning)
        self.assertIsNone(quota.reservation(self.path, "main", "2", self.morning))
        self.claim("late", "3", self.late)
        state, extra, reset = quota.reservation(self.path, "late", "3", self.late)
        self.assertEqual(reset, self.reset)
        self.assertEqual(sum(p["minutes"] for p in state["passes"].values()), 420)
        self.assertEqual(extra["requests"], self.extra_limits)
        quota.settle(self.path, state, extra, 12.5, {"flash-lite": 2, "hydrogen": 1})
        self.assertIsNone(quota.reservation(self.path, "late", "3", self.late))
        self.assertEqual(quota.read(self.path, "2026-11-18")["passes"]["late"]["minutes"], 12.5)
        self.claim("main", "4", self.reset)
        self.assertEqual(set(quota.read(self.path, "2026-11-19")["passes"]), {"main"})

    def test_a_delayed_late_pass_cannot_spend_tomorrows_quota(self):
        self.claim("late", "1", self.reset)
        self.assertFalse(self.path.exists())
        self.claim("late", "1", self.late)
        self.assertIsNone(quota.reservation(self.path, "late", "1", self.reset))
        july = datetime(2026, 7, 19, 6, 7, tzinfo=timezone.utc)
        self.assertEqual(quota.quota_window(july), ("2026-07-18", True, july.replace(hour=7, minute=0)))

    def test_reserved_request_and_time_limits_apply_to_every_attempt(self):
        self.claim("late", "1", self.late)
        _, extra, _ = quota.reservation(self.path, "late", "1", self.late)
        with patch.object(transcribe.time, "monotonic", return_value=100), patch.object(gemini, "requests", {}):
            budget = transcribe.RunBudget(extra, seconds_to_reset=30)
            self.assertEqual(budget.deadline, 130)
            self.assertFalse(budget.reserve(5, "flash", 130))
            self.assertTrue(budget.reserve(5, "hydrogen", 130))
            gemini.requests["hydrogen"] = 1
            self.assertTrue(budget.model_spent("hydrogen"))
            self.assertFalse(budget.reserve(5, "flash-lite", 130))  # next allowed call would reach midnight
            self.assertEqual(budget.minutes_left, 55)
