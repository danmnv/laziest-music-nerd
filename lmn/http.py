"""Tiny HTTP helper on top of the standard library (no extra dependencies)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "LaziestMusicNerd/1.0 (https://github.com/danmnv/laziest-music-nerd)"


class HttpError(Exception):
    def __init__(self, status, body, url):
        # Never put the URL into the message: it can contain an API key or bot token.
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


def request(url, *, method="GET", data=None, json_body=None, headers=None, timeout=30, retries=2):
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            last = HttpError(e.code, text, url)
            if e.code not in (429, 500, 502, 503, 504):
                raise last
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = HttpError(0, repr(e), url)
        time.sleep(3 * (attempt + 1))
    raise last


def get_json(url, **kw):
    return json.loads(request(url, **kw))


def get_bytes(url, timeout=30, max_bytes=10_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(max_bytes + 1)
        if len(data) > max_bytes or not r.headers.get("Content-Type", "").startswith("image/"):
            raise HttpError(0, "not an image or too big", url)
        return data
