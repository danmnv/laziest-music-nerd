import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from lmn import site, tnd
from lmn.enrich import archive_entry
from tests.test_parse import post


class SiteTest(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            data, out = Path(d, "data"), Path(d, "out")
            data.mkdir()
            r = tnd.parse_post(post("A <b> - B & C", ["Album Reviews", "8/10", "noise rock"]))
            r["published"] = datetime.now(timezone.utc).isoformat()
            r.update(ai={"brief": "<script>x</script>"}, previous=[], previous_unsure=0, artist={}, links={})
            (data / "reviews.json").write_text(json.dumps([r]))
            (data / "archive.json").write_text(json.dumps([archive_entry(r)]))
            site.DATA, site.OUT = data, out
            site.build()
            page = (out / "r" / f"{r['id']}.html").read_text()
            self.assertIn("A &lt;b&gt; — B &amp; C", page)
            self.assertNotIn("<script>x</script>", page)
            self.assertIn("Неофициальный фан-проект", page)
            cat = json.loads((out / "catalog.json").read_text())
            self.assertEqual(cat[0]["s"], 8)
            self.assertIn(f'r/{r["id"]}.html', (out / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
