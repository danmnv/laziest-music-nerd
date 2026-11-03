import json
import unittest

from lmn import aoty, rereviews, site


def row(artist, album, found_artist=None, found_title=None, score="7.9", reviews=()):
    return {"input_artist": artist, "input_album": album, "found_artist": found_artist or artist,
            "found_title": found_title or album, "critic_score": score, "critic_reviews": json.dumps(list(reviews))}


PITCHFORK = {"publication": "Pitchfork", "rating": 8.3, "url": "https://pitchfork.com/r"}
TND = {"publication": "The Needle Drop", "rating": 8.0, "url": "https://youtu.be/x"}
ODD = {"publication": "Some Blog", "rating": 9.0, "url": "https://blog"}


class AotyImport(unittest.TestCase):
    def test_only_the_album_asked_for_counts(self):
        archive = [{"id": "m", "artist_name": "M.I.A.", "album": "Maya"},
                   {"id": "d", "artist_name": "Dirty Projectors and Bjork", "album": "Mount Wittenberg Orca"}]
        rows = [row("M.I.A.", "Maya", "maya's home", "i'm you, but happier", reviews=[PITCHFORK]),  # another album
                row("Dirty Projectors and Bjork", "Mount Wittenberg Orca", "Dirty Projectors&Björk", reviews=[PITCHFORK])]
        self.assertEqual(set(aoty.build(rows, archive)), {"d"})

    def test_entry_keeps_known_outlets_with_links_and_fantano_apart(self):
        e = aoty.entry(row("A", "B", reviews=[ODD, TND, PITCHFORK, {"publication": "AllMusic", "rating": 8.0}]))
        self.assertEqual(e, {"s": 79, "tnd": 8.0, "c": [{"outlet": "Pitchfork", "score": "8.3/10", "url": "https://pitchfork.com/r"},
                                                       {"outlet": "AllMusic", "score": "8/10"}]})

    def test_fantano_score_filled_only_where_missing_and_whole(self):
        archive = [{"id": "a"}, {"id": "b", "score": 6}, {"id": "c"}, {"id": "d", "not_good": True}]
        n = aoty.fill_scores(archive, {"a": {"tnd": 8.0}, "b": {"tnd": 8.0}, "c": {"tnd": 8.1}, "d": {"tnd": 2.0}})
        self.assertEqual(n, 1)
        self.assertEqual((archive[0]["score"], archive[0]["score_source"], archive[1]["score"]), (8, "aoty", 6))
        self.assertNotIn("score", archive[2])

    def test_site_shows_aoty_next_to_metacritic_and_fills_empty_critics(self):
        rt = aoty.merge(None, {"s": 79, "c": [{"outlet": "Pitchfork", "score": "8.3/10", "url": "https://pitchfork.com/r"}]})
        rows = dict(site.critics_rows(rt, {"artist_name": "A", "album": "B", "score": 3}))
        self.assertIn("Pitchfork", rows["Критики"])
        self.assertIn("AOTY</a> 79/100", rows["Среднее по рецензиям"])
        self.assertIn("albumoftheyear.org/search", rows["Среднее по рецензиям"])
        self.assertIn("AOTY", rows["Спорно"])  # Fantano 3, AOTY 7.9: the average comes from AOTY when nothing else has one
        wiki = {"wp": True, "critics": [{"outlet": "NME", "score": "4/5"}], "metacritic": 80, "critic_avg10": 8.0}
        both = aoty.merge(wiki, {"s": 79, "c": [{"outlet": "Pitchfork", "score": "8.3/10"}]})
        self.assertEqual(both["critics"], wiki["critics"])  # Wikipedia's outlets stay; AOTY's only where there are none
        self.assertEqual((both["aoty"], both["critic_avg10"]), (79, 8.0))


class Rereviews(unittest.TestCase):
    def test_second_review_and_double_post(self):
        archive = [
            {"id": "p1", "artist_name": "Kanye West", "album": "The Life of Pablo", "published": "2016-02-16T05:34:28Z", "score": 6},
            {"id": "p2", "artist_name": "Kanye West", "album": "The Life of Pablo (Redux)", "published": "2018-01-29T17:06:01Z", "score": 8},
            {"id": "s1", "artist_name": "Sam Smith", "album": "Gloria", "published": "2023-02-09T10:00:00Z", "score": 5},
            {"id": "s2", "artist_name": "Sam Smith", "album": "Gloria", "published": "2023-02-09T12:00:00Z", "score": 5},
            {"id": "v", "artist_name": "Vektor", "album": "Terminal Redux", "published": "2016-05-10T10:00:00Z", "score": 8},
            {"id": "v0", "artist_name": "Vektor", "album": "Terminal", "published": "2012-05-10T10:00:00Z", "score": 6},
        ]
        self.assertEqual(rereviews.link(archive), 3)
        by = {a["id"]: a for a in archive}
        self.assertEqual(by["p2"]["first"], {"id": "p1", "y": "2016", "score": 6, "not_good": False, "classic": False})
        self.assertEqual(by["p1"]["redo"]["id"], "p2")
        self.assertEqual(by["s2"]["dup_of"], "s1")
        self.assertFalse(any(k in by["v"] or k in by["v0"] for k in ("first", "redo")), "Terminal Redux is its own album")
        self.assertEqual(rereviews.link(archive), 0, "a second run changes nothing")

    def test_pages_name_the_other_review(self):
        self.assertEqual(site.again_rows({"first": {"id": "p1", "y": "2016", "score": 6}}),
                         [("Первый обзор", '<a href="p1.html">6/10 (2016)</a>')])
        self.assertEqual(site.again_rows({"redo": {"id": "p2", "y": "2018", "score": 8}})[0][0], "Позже переоценил")
        self.assertEqual(site.again_rows({}), [])


if __name__ == "__main__":
    unittest.main()
