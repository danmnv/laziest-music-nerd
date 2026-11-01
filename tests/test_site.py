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

    def test_pages_for_the_whole_archive_and_artists(self):
        with tempfile.TemporaryDirectory() as d:
            data, out = Path(d, "data"), Path(d, "out")
            data.mkdir()
            old = [{"id": "o1", "url": "https://theneedledrop.com/o1/", "published": "2012-03-01T00:00:00Z", "artist_name": "Swans",
                    "album": "The Seer", "score": None, "genres": ["post-rock"]},
                   {"id": "o2", "url": "https://theneedledrop.com/o2/", "published": "2014-05-01T00:00:00Z", "artist_name": "Swans",
                    "album": "To Be Kind", "score": 10, "video_id": "abcdefghijk"},
                   {"id": "o3", "url": "https://theneedledrop.com/o3/", "published": "2011-01-01T00:00:00Z", "artist_name": "Кино",
                    "album": "Группа крови", "score": 7}]
            (data / "reviews.json").write_text("[]")
            (data / "archive.json").write_text(json.dumps(old))
            site.DATA, site.OUT = data, out
            site.build()
            seer = (out / "r" / "o1.html").read_text()
            self.assertIn('<a href="../a/swans.html">Swans</a> — The Seer', seer)
            self.assertIn("без оценки", seer)
            self.assertIn("Фантано об этом артисте", seer)
            self.assertIn('href="../r/o2.html">To Be Kind</a>', seer)
            self.assertIn("🔎 Google", seer)
            kind = (out / "r" / "o2.html").read_text()
            self.assertIn("https://youtu.be/abcdefghijk", kind)
            self.assertIn("Текст обзора на TND", kind)
            artist = (out / "a" / "swans.html").read_text()
            self.assertLess(artist.index("To Be Kind"), artist.index("The Seer"))  # newest first
            self.assertIn("2 обзора Фантано", artist)
            self.assertEqual(site.slug("Björk"), "bjork")
            self.assertNotEqual(site.slug("坂本龍一 & X"), site.slug("Кино & X"))
            kino = site.slug("Кино")
            self.assertTrue(kino.startswith("x") and (out / "a" / f"{kino}.html").exists())
            cat = {x["i"]: x for x in json.loads((out / "catalog.json").read_text())}
            self.assertEqual(cat["o1"]["k"], "swans")


if __name__ == "__main__":
    unittest.main()
