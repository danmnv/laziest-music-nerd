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

    def test_release_page_lists_the_artists_other_reviews(self):
        r = tnd.parse_post(post("Swans - The Beggar", ["Album Reviews", "7/10", "post-rock"]))
        r.update(previous=[{"album": "To Be Kind", "url": "https://theneedledrop.com/o2/", "score": 10, "published": "2014-05-01"}],
                 previous_unsure=0, artist={}, links={})
        older = {"id": "o2", "album": "To Be Kind", "score": 10, "published": "2014-05-01T00:00:00Z", "artist_name": "Swans"}
        html_ = site.release_page(r, artist_reviews=[r, older])
        self.assertNotIn("История оценок", html_)
        self.assertNotIn("Фантано раньше", html_)  # the list below says it, each album linked to its page here
        self.assertIn('<h2>Фантано об этом артисте</h2>', html_)
        self.assertIn('<a href="../r/o2.html">To Be Kind</a>', html_)
        first = site.release_page(dict(r, previous=[]), artist_reviews=[r])
        self.assertIn("<dt>Фантано раньше</dt><dd>обозревает впервые", first)
        self.assertNotIn("Фантано об этом артисте", first)

    def test_archive_card_video_from_notes(self):
        a = {"id": "k", "url": "https://theneedledrop.com/x", "published": "2022-08-18", "artist_name": "Black Thought & Danger Mouse",
             "album": "Cheat Codes", "score": 8, "genres": []}
        html_ = site.archive_page(a, [a], note={"video_id": "UeSwqepnAX0", "blurb": "b", "fav": [], "bc": "https://x.bandcamp.com/album/y"})
        self.assertIn('<a class="btn" href="https://youtu.be/UeSwqepnAX0">▶ Видеообзор</a>', html_)
        self.assertIn('<a class="btn" href="https://x.bandcamp.com/album/y">Bandcamp</a>', html_)  # Fantano's "Listen:" link
        self.assertIn('>Текст обзора на TND</a>', html_)

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
        self.assertEqual(crit, ["Pitchfork 10/10", "AllMusic 4.5/5", "Metacritic 80/100"])
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
        # one outlet a line, authority order, linked to the review when Wikipedia cites it; the aggregators after them
        # without a cited review, the outlet's home page; Wikipedia named only on the charts line (Daniil, 2026-11-01)
        self.assertIn('<dt>Критики</dt><dd><ul class="critics"><li><a href="https://pitchfork.com">Pitchfork</a> — 10/10</li>'
                      '<li><a href="https://www.allmusic.com">AllMusic</a> — 4.5/5</li></ul></dd>'
                      '<dt>Среднее по рецензиям</dt><dd><a href="https://www.metacritic.com">Metacritic</a> 80/100</dd>', html_)
        self.assertEqual(html_.count("Википедия"), 1)
        self.assertIn('US Platinum <span class="muted">· <a href="https://en.wikipedia.org/wiki/Kid_A">Википедия</a></span>', html_)
        linked = dict(self.RT, critics=[{"outlet": "Pitchfork", "score": "10/10", "url": "https://pitchfork.com/r"},
                                        {"outlet": "NME", "score": "5/5", "url": "javascript:alert(1)"}], mc_url="https://www.metacritic.com/m")
        html_ = site.archive_page(a, [a], linked)
        self.assertIn('<li><a href="https://pitchfork.com/r">Pitchfork</a> — 10/10</li><li><a href="https://www.nme.com">NME</a> — 5/5</li>', html_)
        self.assertIn('<a href="https://www.metacritic.com/m">Metacritic</a> 80/100', html_)
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
        older = {"id": "boxer", "url": "https://tnd/boxer", "published": "2010-01-01", "artist_name": "The National", "album": "High Violet", "score": 7}
        album = {"dz": 42, "cv": "https://cdn/cover.jpg", "y": "2023", "min": 46, "t": [["Eucalyptus", 260], ["Tropic Morning News", 301]]}
        html_ = site.archive_page(a, [a, older], None, None, n, album=album)
        # what the bot's card knows: year, tracks, minutes, n-th review, «Все платформы», and the tracklist with ★
        self.assertIn("First Two Pages <span class=\"muted\">(2023)</span></h1>", html_)
        self.assertIn("2 трека · 46 мин · обзор 2023-05-05 · 2-й из 2 обзоров артиста", html_)
        self.assertIn('href="https://album.link/https://www.deezer.com/album/42">Все платформы</a>', html_)
        self.assertIn("<ol><li>Eucalyptus 4:20 ★</li><li>Tropic Morning News 5:01 ★</li></ol>", html_)
        self.assertIn('<dt>Фантано в описании ролика</dt><dd><q lang="en">If you found &lt;it&gt; too colorful</q></dd>', html_)
        self.assertIn('<img class="cover" src="https://cdn/cover.jpg" alt="">\n<h1>', html_)  # the cover first
        # the favourites come after the buttons, each player behind a tap; a track with no player is just its title
        self.assertLess(html_.index('class="btns"'), html_.index('<h2 id="fav">Любимые треки Фантано</h2>'))
        self.assertEqual(html_.count("<details>"), 2)
        self.assertEqual(html_.count("widget.deezer.com/widget/auto/track/"), 1)
        self.assertIn('src="https://widget.deezer.com/widget/auto/track/111"', html_)
        self.assertIn('src="https://embed.music.apple.com/us/album/x/123?i=456"', html_)
        self.assertIn('<li><span class="trk">Alien</span></li>', html_)
