import unittest
from unittest import mock
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
        # the bot's score line: «N-й из M обзоров артиста» instead of «Фантано раньше» (owner, 2026-11-08)
        self.assertIn("🟡 7/10 · darkwave, dream pop · 44 мин · 3-й из 3 обзоров артиста\n\n", c)
        self.assertNotIn("Фантано раньше", c)
        # «Кто» and «Обзор» (was «Описание») with no blank line between them
        self.assertIn("<b>Кто:</b> ирландская рок-группа, пятый альбом\n<b>Обзор:</b> Ирландцы расширили звук.\n\n", c)
        self.assertLessEqual(card.tg_len(c), 1024)
        line = card.list_line(r)
        self.assertTrue(line.startswith("🟡 7 · <a href="))
        self.assertTrue(line.endswith("Fontaines D.C. — Dopamine Chamber</a> · darkwave · 44 мин"))
        kb = card.buttons(r, with_callbacks=True)
        # buttons only for actions; the links are the caption's last line, under the tracklist (owner, 2026-11-02)
        self.assertTrue(all("callback_data" in b for row in kb for b in row))
        # as the bot's card: the artist's albums next to «🔔 Следить» (owner, 2026-11-08)
        self.assertIn([{"text": "🔔 Следить", "callback_data": f"f:{r['id']}"},
                       {"text": "💿 Альбомы артиста", "callback_data": f"da:{r['id']}"}], kb)
        # as the bot's card (worker MARK_ROWS): «♡ Понравилось» is its own mark, «Отложить» is «⏳ Послушать потом»
        self.assertEqual([[b["callback_data"] for b in row] for row in kb[:2]],
                         [[f"m:{r['id']}:done", f"lk:{r['id']}"], [f"m:{r['id']}:later", f"m:{r['id']}:nope"]])
        # a vote button carries the word's index in MOODS (append-only), not its place on the card
        self.assertIn([{"text": "для фона за работой: да", "callback_data": f"w:{r['id']}:14:y"},
                       {"text": "нет", "callback_data": f"w:{r['id']}:14:n"}], kb)
        self.assertEqual([[b["text"] for b in row] for row in kb[:2]],
                         [["✓ Слушал", "♡ Понравилось"], ["⏳ Послушать потом", "✗ Не моё"]])
        self.assertEqual(card.buttons(r), [])
        self.assertEqual([t for t, _ in card.link_items(r)],
                         ["Видеообзор", "искать в YouTube Music", "искать в SoundCloud", "Bandcamp", "оценки на AOTY"])
        self.assertTrue(c.endswith("\n" + card.links_line(r)))
        self.assertNotIn("Все платформы", c)
        bare = dict(r, links={"bandcamp": "https://bandcamp.com/search?q=x", "ytmusic": "https://y", "apple": "https://music.apple.com/us/album/x/1"})
        # no Google search where no Bandcamp page is known (owner, 2026-11-08)
        self.assertEqual(card.link_items(bare)[2:5], [("Apple Music", "https://music.apple.com/us/album/x/1"),
            ("искать в SoundCloud", "https://soundcloud.com/search?q=Fontaines%20D.C.%20Dopamine%20Chamber"),
            ("оценки на AOTY", "https://www.albumoftheyear.org/search/?q=Fontaines+D.C.+Dopamine+Chamber")])
        self.assertFalse(card.links_line(r).startswith("<b>"))  # no «Ссылки:» word
        self.assertTrue(all(len(b["callback_data"].encode()) <= 64 for row in kb for b in row if "callback_data" in b))
        txt = card.pinned_text([r])
        self.assertIn("Dopamine Chamber", txt)
        newer = [dict(r, id=f"n{i}", album=f"Newer {i}", published=f"2027-01-{i + 1:02d}T10:00:00Z") for i in range(30)]
        txt = card.pinned_text([r] + newer)
        self.assertNotIn("Dopamine Chamber", txt)  # the 31st from the top is gone
        self.assertEqual(txt.count("Newer "), 30)
        self.assertIn('<a href="https://t.me/laziest_music_nerd_bot">Бот</a>: поиск по архиву', txt)
        # a short welcome and how the channel and the bot work, then the list (owner, 2026-11-02)
        self.assertTrue(txt.startswith("<b>Привет!</b> 👋 Здесь мы знакомимся с новой музыкой"))
        self.assertIn("Неофициальный проект", txt)
        self.assertLess(txt.index("<b>Бот</b>"), txt.index("<b>Последние 30 обзоров Фантано</b>\n\n"))
        self.assertLess(txt.index("Newer 29"), txt.index("Newer 0"))
        with mock.patch.object(card, "WORKER_LIVE", True), mock.patch.object(card, "BOT_USERNAME", "bot"):
            self.assertIn(f'<a href="https://t.me/bot?start=a_{r["id"]}">Fontaines D.C. — Dopamine Chamber</a>', card.list_line(r))
        with mock.patch.object(card, "SITE_LIVE", True):
            cap = card.caption(r)
            self.assertIn("<b>Fontaines D.C. — Dopamine Chamber</b>", cap)  # copyable: not a link
            self.assertTrue(cap.endswith(f'\n🌐 <a href="{card.SITE_URL}/r/{r["id"]}.html">На нашем сайте</a>'))

    def test_pin_intro_is_the_same_in_the_worker(self):
        # The owner's marks edit the pin through the Worker, new reviews through check.py: two texts would make it flip
        import pathlib
        import re
        js = (pathlib.Path(__file__).parent.parent / "worker/src/index.js").read_text(encoding="utf-8")
        body = re.search(r"function pinIntro\(env\) \{.*?return (.*?);\n\}", js, re.S).group(1)
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"|`((?:[^`\\]|\\.)*)`', body)
        text = "".join(a or b for a, b in parts).replace("\\n", "\n").replace("${bot}", "BOT")
        with mock.patch.object(card, "BOT_USERNAME", "BOT"):
            self.assertEqual(text, card.pin_intro())

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
        self.assertIn("🟡 7/10 · darkwave · 2 трека · 44 мин", c)
        self.assertIn("1. Big Fire 3:21 ★", c)
        self.assertIn("2. Favourite 1:02</blockquote>", c)
        self.assertIn("</blockquote>\n<a href=", c)  # the links right under the tracklist (owner, 2026-11-02)
        # paragraphs, as in the bot; nothing about the artist's other reviews on a first one
        self.assertIn("44 мин\n\n<b>Обзор:</b> Бриф.\n<blockquote", c)
        self.assertIn("<blockquote expandable>", c)
        self.assertEqual(card.plural_tracks(11), "11 треков")
        self.assertEqual(card.plural_tracks(21), "21 трек")
        self.assertEqual(card.plural_tracks(23), "23 трека")
        # a huge tracklist and brief must still fit, tracklist shrinks first
        r["tracks"] = [{"title": f"Track number {i} with a long name", "sec": 200} for i in range(40)]
        r["ai"] = {"brief": "Очень длинный бриф. " * 40}
        c = card.caption(r)
        self.assertLessEqual(card.tg_len(c), 1024)
        self.assertIn("<b>Обзор:</b>", c)
        self.assertIn('<a href="https://youtu.be/UzvthnAU6nc">Видеообзор</a>', c)  # the links stay when the tracklist shrinks
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


class CardExtrasTest(unittest.TestCase):
    R = {"id": "v", "artist_name": "Rachel Chinouriri", "album": "I think I spoke too soon", "score": 7, "genres": ["synthpop"],
         "previous": [], "previous_unsure": 0, "artist": {}, "links": {}, "ai": {}}

    def test_without_a_description_fantanos_line_and_a_promise(self):
        c = card.caption(dict(self.R, blurb="A big step forward.", brief_pending=1))
        self.assertIn("<b>Фантано под видео:</b> <i>A big step forward.</i>", c)
        self.assertIn("Обзор ещё пишется", c)
        c = card.caption(dict(self.R, blurb="A big step forward.", brief_pending=1, ai={"brief": "Бриф."}))
        self.assertNotIn("Фантано под видео", c)
        self.assertNotIn("ещё пишется", c)

    def test_three_critics_in_priority_order_then_metacritic(self):
        rt = {"wp": "X", "metacritic": 77, "mc_url": "https://www.metacritic.com/x", "critics": [
            {"outlet": "Pitchfork", "score": "7.3/10", "url": "https://pitchfork.com/r"}, {"outlet": "NME", "score": "4/5"},
            {"outlet": "Rolling Stone", "score": "3.5/5", "url": "https://rs/r"}, {"outlet": "The Guardian", "score": "4/5"}]}
        crit = card.critics_from(rt)
        self.assertEqual([c["o"] for c in crit], ["Pitchfork", "NME", "Rolling Stone", "Metacritic"])
        c = card.caption(dict(self.R, critics=crit))
        self.assertIn("<b>Критики:</b> Pitchfork 7.3/10 · NME 4/5 · Rolling Stone 3.5/5 · Metacritic 77/100", c)
        self.assertEqual(card.critics_from({"critics": []}), [])


if __name__ == "__main__":
    unittest.main()
