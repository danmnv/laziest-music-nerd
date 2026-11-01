import unittest
from datetime import datetime, timezone

from lmn import card, tnd


def post(title, tags, text="", canonical="https://www.youtube.com/watch?v=UzvthnAU6nc", pid="6ae16e7060a520b7b082e3e1"):
    return {"id": pid, "title": title, "slug": "x", "url": "https://theneedledrop.com/album-reviews/x/",
            "published_at": "2026-10-22T07:22:16.000-04:00", "canonical_url": canonical,
            "tags": [{"name": t} for t in tags], "plaintext": text}


class ParseTest(unittest.TestCase):
    def test_regular(self):
        r = tnd.parse_post(post("Fontaines D.C. - Dopamine Chamber",
                                ["Album Reviews", "Edited by Cassidy", "7/10", "fontaines d.c.", "darkwave", "dream pop"],
                                "…which is why I'm feeling a light-to-decent 7 on this one.\n\nAnthony Fantano, Fontaines D.C., forever."))
        self.assertEqual((r["artist_name"], r["album"], r["score"]), ("Fontaines D.C.", "Dopamine Chamber", 7))
        self.assertEqual(r["genres"], ["darkwave", "dream pop"])
        self.assertEqual(r["score_note"], "light-to-decent")
        self.assertEqual(r["video_id"], "UzvthnAU6nc")
        for link in ("https://www.youtube.com/live/UzvthnAU6nc?si=x", "https://youtube.com/shorts/UzvthnAU6nc"):
            self.assertEqual(tnd.parse_post(post("A - B", ["Album Reviews"], canonical=link))["video_id"], "UzvthnAU6nc")

    def test_not_good(self):
        r = tnd.parse_post(post("Kid Rock's Halfway 2 Jesus is NOT GOOD", ["Album Reviews", "Edited by Isaiah", "kid rock", "not good"]))
        self.assertEqual((r["artist_name"], r["album"], r["not_good"], r["score"]), ("Kid Rock", "Halfway 2 Jesus", True, None))
        self.assertEqual(r["genres"], [])
        r = tnd.parse_post(post("Benny Blanco's Hermoso is BAD", ["Album Reviews", "not good"]))
        self.assertEqual((r["artist_name"], r["album"]), ("Benny Blanco", "Hermoso"))

    def test_ep_and_guest(self):
        r = tnd.parse_post(post("Zach Bryan - Young Manhood and Other Donatable Organs EP",
                                ["Album Reviews", "zach bryan", "ep review", "country rock", "americana", "6/10"]))
        self.assertEqual((r["album"], r["type"], r["score"]), ("Young Manhood and Other Donatable Organs", "ep", 6))
        self.assertEqual(r["genres"], ["country rock", "americana"])
        r = tnd.parse_post(post("Kyle Gordon - Kyle Gordon Is Everywhere [GUEST REVIEW]", ["Album Reviews", "giggens", "kyle gordon", "8/10"]))
        self.assertTrue(r["guest"])
        self.assertEqual(r["album"], "Kyle Gordon Is Everywhere")
        r = tnd.parse_post(post("TND Staff Album Review: ‘Hauntings’ by Richard Barbieri", ["Album Reviews"]))
        self.assertEqual((r["artist_name"], r["album"], r["guest"]), ("Richard Barbieri", "Hauntings", True))

    def test_verdict_from_text_when_no_tag(self):
        r = tnd.parse_post(post("Arcade Fire - Pink Elephant", ["Album Reviews", "arcade fire"],
                                "blah blah. I'm feeling a strong 6 on this one. Anthony Fantano, Arcade Fire, forever."))
        self.assertEqual((r["score"], r["score_note"]), (6, "strong"))
        r = tnd.parse_post(post("Don Toliver - OCTANE ALBUM REVIEW", ["Album Reviews"], "This record is NOT GOOD. Forever."))
        self.assertEqual((r["album"], r["not_good"]), ("OCTANE", True))

    def test_caption_and_list(self):
        r = tnd.parse_post(post("Fontaines D.C. - Dopamine Chamber", ["Album Reviews", "7/10", "darkwave", "dream pop"]))
        r.update(ai={"brief": "Ирландцы расширили звук.", "who": "ирландская рок-группа, пятый альбом", "moods": ["для работы за столом"]},
                 previous=[{"album": "Romance", "score": 7}, {"album": "Skinty Fia", "score": 6}], previous_unsure=0,
                 artist={"begin": "2014"}, duration_min=44,
                 links={"bandcamp": "https://b", "ytmusic": "https://y", "songlink": "https://album.link/x"})
        c = card.caption(r)
        self.assertIn("<b>Fontaines D.C. — Dopamine Chamber</b>", c)
        self.assertIn("🟡 7/10 · darkwave, dream pop · 44 мин", c)
        self.assertIn("Romance — 7; Skinty Fia — 6", c)
        self.assertLessEqual(card.tg_len(c), 1024)
        line = card.list_line(r)
        self.assertTrue(line.startswith("🟡 7 · <a href="))
        self.assertTrue(line.endswith("Fontaines D.C. — Dopamine Chamber</a> · darkwave · 44 мин"))
        kb = card.buttons(r, with_callbacks=True)
        self.assertEqual([b["text"] for b in kb[0]], ["Bandcamp", "🔎 YouTube Music"])
        self.assertEqual(kb[1][0], {"text": "Все платформы", "url": "https://album.link/x"})
        self.assertIn([{"text": "🔔 Следить за артистом", "callback_data": f"f:{r['id']}"}], kb)
        bare = dict(r, links={"bandcamp": "https://bandcamp.com/search?q=x", "ytmusic": "https://y"})
        kb = card.buttons(bare)
        self.assertEqual([b["text"] for b in kb[0]], ["🔎 Bandcamp", "🔎 YouTube Music"])
        self.assertEqual(kb[1][0], {"text": "🔎 Google", "url": "https://www.google.com/search?q=Fontaines+D.C.+Dopamine+Chamber"})
        self.assertTrue(all(len(b["callback_data"].encode()) <= 64 for row in kb for b in row if "callback_data" in b))
        txt = card.pinned_text([r], now=datetime(2026, 10, 31, tzinfo=timezone.utc))
        self.assertIn("Dopamine Chamber", txt)
        self.assertNotIn("Dopamine Chamber", card.pinned_text([r], now=datetime(2027, 1, 31, tzinfo=timezone.utc)))

    def test_person_begin_is_not_activity(self):
        r = {"previous": [{"album": "X", "score": None}], "previous_unsure": 0, "artist": {"type": "Person", "begin": "1996"}}
        self.assertEqual(card.fantano_before(r), "X — ?")
        r["artist"] = {"type": "Group", "begin": "1996"}
        self.assertEqual(card.fantano_before(r), "X — ?; активны с 1996")

    def test_smartlink_hosts(self):
        from lmn.musicbrainz import is_smartlink
        self.assertTrue(is_smartlink("https://underscores.lnk.to/u"))
        self.assertTrue(is_smartlink("https://www.ffm.to/x"))
        self.assertTrue(is_smartlink("https://distrokid.com/hyperfollow/a/b"))
        self.assertFalse(is_smartlink("https://distrokid.com/x"))
        self.assertFalse(is_smartlink("https://open.spotify.com/album/1"))
        self.assertFalse(is_smartlink("https://example.com/lnk.to"))

    def test_tracklist_and_limits(self):
        r = tnd.parse_post(post("Fontaines D.C. - Dopamine Chamber", ["Album Reviews", "7/10", "darkwave"]))
        r.update(previous=[], previous_unsure=0, artist={}, links={}, duration_min=44, video_id="UzvthnAU6nc",
                 tracks=[{"title": "Big Fire", "sec": 201}, {"title": "Favourite", "sec": 62}],
                 ai={"brief": "Бриф.", "best_tracks": ["big fire"]})
        c = card.caption(r)
        self.assertIn("🟡 7/10 · darkwave · 2 трека, 44 мин", c)
        self.assertIn("1. Big Fire 3:21 ★", c)
        self.assertIn("2. Favourite 1:02</blockquote>", c)
        self.assertIn("<blockquote expandable>", c)
        self.assertEqual(card.plural_tracks(11), "11 треков")
        self.assertEqual(card.plural_tracks(21), "21 трек")
        self.assertEqual(card.plural_tracks(23), "23 трека")
        # a huge tracklist and brief must still fit, tracklist shrinks first
        r["tracks"] = [{"title": f"Track number {i} with a long name", "sec": 200} for i in range(40)]
        r["ai"] = {"brief": "Очень длинный бриф. " * 40}
        c = card.caption(r)
        self.assertLessEqual(card.tg_len(c), 1024)
        self.assertIn("<b>Бриф:</b>", c)
        kb = card.buttons(r)
        self.assertEqual(kb[-1][-1], {"text": "▶ Видеообзор", "url": "https://youtu.be/UzvthnAU6nc"})
        self.assertNotIn("Видеообзор на YouTube", c)

    def test_first_review(self):
        r = {"previous": [], "previous_unsure": 0, "artist": {}}
        self.assertEqual(card.fantano_before(r), "обозревает впервые")


class OldTitleTest(unittest.TestCase):
    def test_tidy_album(self):
        self.assertEqual(tnd.tidy_album("Kaputt ‡ REVIEW"), "Kaputt")
        self.assertEqual(tnd.tidy_album('"Stamp" ‡ MP3 / REVIEW'), '"Stamp"')
        self.assertEqual(tnd.tidy_album("Who's Next (CLASSIC REVIEW)"), "Who's Next")
        self.assertEqual(tnd.tidy_album("Homeland | REVIEW"), "Homeland")
        self.assertEqual(tnd.tidy_album("Public Strain ‡"), "Public Strain")
        self.assertEqual(tnd.tidy_album("Black Review Club"), "Black Review Club")
        self.assertEqual(tnd.tidy_album("Preview"), "Preview")
        self.assertEqual(tnd.tidy_album("The Interview"), "The Interview")
        self.assertEqual(tnd.parse_title("Destroyer - Kaputt ‡ REVIEW")["album"], "Kaputt")

    def test_tracks(self):
        self.assertTrue(tnd.is_track('"Facts"'))
        self.assertFalse(tnd.is_track('"Luciferian Towers"', score=5))
        self.assertFalse(tnd.is_track("Kaputt"))
        p = tnd.parse_post(post('Kanye West - "Facts"', ["Kanye West", "hip hop"]))
        self.assertTrue(p["track"])
        a = tnd.tidy_entry({"album": '"Discoverer" ‡ REVIEW', "score": None})
        self.assertEqual(a, {"album": '"Discoverer"', "score": None, "track": True})


if __name__ == "__main__":
    unittest.main()
