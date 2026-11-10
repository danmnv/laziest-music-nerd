"""What GitHub Actions tell the Worker so that the owner hears about a silent stop (worker/src/watchdog.mjs).

heartbeat(): every check of new reviews says "alive"; when that goes quiet for a few hours (Actions stopped
altogether, as on 2026-11-08), the Worker messages the owner. alert(kind): a job that can't go on and wouldn't turn
red asks the Worker to tell the owner one of its fixed texts. Neither ever fails a run: the Worker being down is
only printed.
"""
import hashlib
import os
from pathlib import Path

from . import http

DATA = Path(os.environ.get("DATA_DIR", "data"))


def worker(data=None):
    """The Worker's address and the secret GitHub Actions call it with, or (None, None) before the Worker exists."""
    f = (data or DATA) / "worker_url.txt"
    url = f.read_text().strip() if f.exists() else None
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not (url and token):
        return None, None
    # same derivation as the deploy workflow, so no extra secret is needed
    return url.rstrip("/"), hashlib.sha256(f"{token}:actions".encode()).hexdigest()[:48]


def _post(path, body, data=None):
    url, secret = worker(data)
    if not url:
        return False
    try:
        http.request(url + path, method="POST", json_body=body, headers={"Authorization": f"Bearer {secret}"},
                     timeout=15, retries=1)
        return True
    except Exception as ex:  # never the URL or the secret in the log
        print(f"::warning::worker {path} unavailable: {type(ex).__name__}")
        return False


def heartbeat(data=None):
    return _post("/api/heartbeat", {"job": "check"}, data)


def alert(kind, code=None, data=None):
    return _post("/api/alert", {"kind": kind, **({"code": int(code)} if code else {})}, data)
