import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from lmn import card, site, tnd
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


class CriticsTest(unittest.TestCase):
    RT = {"checked": "2026-11-01T00:00:00Z", "wp": "Kid A", "wp_url": "https://en.wikipedia.org/wiki/Kid_A", "metacritic": 80,
          "adm": None, "critics": [{"outlet": "Pitchfork", "score": "10/10", "s10": 10}, {"outlet": "AllMusic", "score": "4.5/5", "s10": 9}],
          "charts": {"US": 1, "UK": 1}, "certs": [{"region": "US", "award": "Platinum"}]}

    def test_slug_keeps_latin_letters_nfkd_cannot_split(self):
        self.assertEqual(site.slug("Mø"), "mo")
        self.assertEqual(site.slug("MØ"), "mo")
        self.assertEqual(site.slug("Altın Gün"), "altingun")

    def test_parts(self):
        crit, sales = site.critics_parts(self.RT)
        self.assertEqual(crit, ["Metacritic 80", "Pitchfork 10/10", "AllMusic 4.5/5"])
        self.assertEqual(sales, ["US #1", "UK #1", "US Platinum"])
        self.assertEqual(site.critics_parts({"checked": "x", "wp": None}), ([], []))
        self.assertEqual(site.critics_parts(None), ([], []))

    def test_contested(self):
        rt = dict(self.RT, critic_avg10=8.0, critic_avg_n=None)
        self.assertEqual(site.contested({"score": 3}, rt), "Фантано 3/10, критики 8/10 (Metacritic)")
        self.assertEqual(site.contested({"score": 9}, dict(rt, critic_avg10=4.5, critic_avg_n=6)), "Фантано 9/10, критики 4.5/10 (среднее по 6 изданиям)")
        self.assertIsNone(site.contested({"score": 5}, rt))  # 3 points apart
        self.assertIsNone(site.contested({"score": 3, "guest": True}, rt))
        self.assertIsNone(site.contested({"score": None, "not_good": True}, rt))
        self.assertIsNone(site.contested({"score": 3}, dict(rt, critic_avg10=None)))
        a = {"id": "k", "url": "u", "published": "2020-01-01", "artist_name": "X", "album": "Y", "score": 3, "genres": []}
        self.assertIn('<dt>Спорно</dt><dd><span class="contested">⚡ Фантано 3/10, критики 8/10 (Metacritic)</span>', site.archive_page(a, [a], rt))

    def test_archive_page_shows_them_with_attribution(self):
        a = {"id": "k", "url": "https://theneedledrop.com/x", "published": "2020-01-01", "artist_name": "Radiohead", "album": "Kid A",
             "score": 10, "not_good": False, "classic": False, "genres": []}
        html_ = site.archive_page(a, [a], self.RT)
        self.assertIn("<dt>Критики</dt><dd>Metacritic 80 · Pitchfork 10/10 · AllMusic 4.5/5", html_)
        self.assertIn('href="https://en.wikipedia.org/wiki/Kid_A">по данным Википедии</a>', html_)
        bare = site.archive_page(a, [a])  # only the hidden mood row, filled by app.js from visitors' votes
        self.assertIn('<dl><dt class="moods-h" hidden>Когда слушать</dt><dd class="moods" hidden></dd></dl>', bare)
        self.assertNotIn("<dt>", bare)


class AotyLink(unittest.TestCase):
    def test_search_link_on_cards_and_pages(self):
        r = {"artist_name": "Radiohead", "album": "Kid A", "links": {"songlink": "https://album.link/x"}}
        top, alls = card.link_rows(r)
        self.assertEqual(alls[-1], ("🔎 AOTY", "https://www.albumoftheyear.org/search/?q=Radiohead+Kid+A"))
        self.assertIn(("🔎 Оценки на AOTY", "https://www.albumoftheyear.org/search/?q=Radiohead+Kid+A"),
                      site.search_buttons("Radiohead", "Kid A"))


if __name__ == "__main__":
    unittest.main()


class Lists(unittest.TestCase):
    def test_rows_link_each_video(self):
        a = {"id": "okc", "url": "https://tnd/okc", "published": "2017-01-01", "artist_name": "Radiohead", "album": "OK Computer", "score": 10}
        b = [{"text": "№1 из 9 в «Radiohead: от худшего к лучшему» (2017)", "url": "https://www.youtube.com/watch?v=uu8&t=984"}]
        self.assertIn('<dt>У Фантано в списках</dt><dd>🏆 <a href="https://www.youtube.com/watch?v=uu8&amp;t=984">№1 из 9 в «Radiohead: от худшего к лучшему» (2017)</a></dd>',
                      site.archive_page(a, [a], None, b))


class Notes(unittest.TestCase):
    def test_blurb_and_players(self):
        a = {"id": "nat", "url": "https://tnd/nat", "published": "2023-05-05", "artist_name": "The National", "album": "First Two Pages", "score": 6}
        n = {"blurb": "If you found <it> too colorful", "fav": [{"t": "EUCALYPTUS", "dz": 111}, {"t": "ALIEN", "dz": None}, {"t": "X"},
                                                                  {"t": "TROPIC", "dz": 0, "am": "us/album/x/123?i=456"}]}
        html_ = site.archive_page(a, [a], None, None, n, cover="https://cdn/cover.jpg")
        self.assertIn('<dt>Фантано в описании ролика</dt><dd><q lang="en">If you found &lt;it&gt; too colorful</q></dd>', html_)
        self.assertIn('<img class="cover" src="https://cdn/cover.jpg" alt="">\n<h1>', html_)  # the cover first
        # the favourites come after the buttons, each player behind a tap; a track with no player is just its title
        self.assertLess(html_.index('class="btns"'), html_.index('<h2 id="fav">Любимые треки Фантано</h2>'))
        self.assertEqual(html_.count("<details>"), 2)
        self.assertEqual(html_.count("widget.deezer.com/widget/auto/track/"), 1)
        self.assertIn('src="https://widget.deezer.com/widget/auto/track/111"', html_)
        self.assertIn('src="https://embed.music.apple.com/us/album/x/123?i=456"', html_)
        self.assertIn('<li><span class="trk">ALIEN</span></li>', html_)
