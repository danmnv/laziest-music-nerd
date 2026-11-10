"""The watchdog's calls from GitHub Actions to the Worker (lmn/watch.py): never a failed run, never a secret in the log."""
import contextlib
import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lmn import http, llm, watch


class Watch(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.data = Path(d.name)
        p = mock.patch.object(watch, "DATA", self.data)
        p.start()
        self.addCleanup(p.stop)

    def test_without_a_worker_nothing_is_called(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}), mock.patch.object(http, "request") as req:
            self.assertFalse(watch.heartbeat())
            self.assertFalse(watch.alert("llm", 402))
        req.assert_not_called()

    def test_heartbeat_and_alert_go_to_the_worker_with_the_actions_secret(self):
        (self.data / "worker_url.txt").write_text("https://w.example/\n")
        secret = hashlib.sha256(b"tok:actions").hexdigest()[:48]
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}), mock.patch.object(http, "request", return_value="{}") as req:
            self.assertTrue(watch.heartbeat())
            self.assertTrue(watch.alert("llm", 402))
        (a, ka), (b, kb) = [(c.args, c.kwargs) for c in req.call_args_list]
        self.assertEqual((a[0], ka["method"], ka["headers"]["Authorization"]), ("https://w.example/api/heartbeat", "POST", f"Bearer {secret}"))
        self.assertEqual((b[0], kb["json_body"]), ("https://w.example/api/alert", {"kind": "llm", "code": 402}))

    def test_a_worker_that_is_down_is_only_printed_without_the_address_or_the_secret(self):
        (self.data / "worker_url.txt").write_text("https://w.example")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok"}), contextlib.redirect_stdout(out), \
                mock.patch.object(http, "request", side_effect=http.HttpError(0, "down", "https://w.example/api/heartbeat")):
            self.assertFalse(watch.heartbeat())
        self.assertIn("::warning::", out.getvalue())
        self.assertNotIn("w.example", out.getvalue())
        self.assertNotIn(hashlib.sha256(b"tok:actions").hexdigest()[:48], out.getvalue())

    def test_the_paid_router_refusing_the_key_is_remembered_for_the_owner(self):
        for status in (402, 401):
            llm._dead.clear()
            llm.stats.pop("denied", None)
            with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "k"}), \
                    mock.patch.object(llm.http, "get_json", side_effect=llm.http.HttpError(status, "{}", "u")):
                self.assertIsNone(llm.ask("selectel", "A - B", "text", model="m1", lang="both", sleep=lambda s: None))
            self.assertEqual(llm.stats.get("denied"), status)
        llm._dead.clear()
        llm.stats.pop("denied", None)
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "g"}), \
                mock.patch.object(llm.http, "get_json", side_effect=llm.http.HttpError(401, "{}", "u")):
            llm.ask("groq", "A - B", "text", sleep=lambda s: None)
        self.assertNotIn("denied", llm.stats)  # a free provider's wrong key is not the owner's money
        llm._dead.clear()


if __name__ == "__main__":
    unittest.main()
