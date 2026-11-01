import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from lmn import ratings

ARTICLE = """{{Infobox album
| name = Brat
| type = studio
| artist = [[Charli XCX]]
}}
'''''Brat''''' is an album.
==Critical reception==
{{Album ratings
| ADM = 8.6/10<ref>x</ref>
| MC = 95/100<ref name=a/>
| rev1 = [[AllMusic]]
| rev1Score = {{Rating|4.5|5}}<ref>{{cite web|url=x|title=y}}</ref>
| rev2 = ''[[The Needle Drop]]''
| rev2Score = 8/10
| rev3 = ''[[Pitchfork (website)|Pitchfork]]''
| rev3Score = 9.3/10
| rev4 = ''[[Entertainment Weekly]]''
| rev4Score = A−
| rev5 = Some Blog
| rev5Score = favorable
| rev6 = ''[[The Guardian]]''
| rev6Score = {{Rating|5|5}}
| rev7 = ''[[NME]]''
| rev7Score = {{Rating|4|5}}
| rev8 = ''[[Rolling Stone]]''
| rev8Score = {{Rating|4.5|5}}
}}
==Charts==
{{Album chart|Billboard200|3|artist=Charli XCX|rowheader=true}}
{{Album chart|UK2|1|date=20240615|rowheader=true}}
{{Album chart|Australia|2}}
==Certifications==
{{Certification Table Top}}
{{Certification Table Entry|region=United Kingdom|type=album|award=Platinum|certyear=2024|salesamount=|relyear=2024}}
{{Certification Table Entry|region=United States|type=album|award=Platinum|number=2|certref=<ref>{{cite web|url=x}}</ref>}}
{{Certification Table Entry|region=Japan|type=album|award=|salesamount=12,000}}
{{Certification Table Bottom}}
"""


class ParseTest(unittest.TestCase):
    def test_parse_and_summary(self):
        p = ratings.parse(ARTICLE)
        names = [c["outlet"] for c in p["critics"]]
        self.assertNotIn("The Needle Drop", names)  # Fantano is not "other critics"
        self.assertEqual(p["metacritic"], 95)
        self.assertEqual(p["adm"], 8.6)
        self.assertEqual(p["charts"], {"US": 3, "UK": 1})
        self.assertEqual(p["certs"][0], {"region": "UK", "award": "Platinum"})
        self.assertEqual(p["certs"][1], {"region": "US", "award": "2× Platinum"})
        self.assertEqual(p["certs"][2], {"region": "JP", "award": "", "sales": "12,000"})
        s = ratings.summarize(p)
        self.assertEqual([c["outlet"] for c in s["critics"]], ["Pitchfork", "AllMusic", "NME", "Rolling Stone", "The Guardian"])
        self.assertEqual(s["critics"][1]["score"], "4.5/5")
        self.assertEqual(s["critics"][1]["s10"], 9.0)
        self.assertEqual(s["critic_avg10"], 9.5)  # Metacritic wins over own average
        e = dict(s, wp="Brat (album)")
        self.assertEqual(ratings.card_line(e), "Критики: Metacritic 95 · Pitchfork 9.3/10 · AllMusic 4.5/5 · NME 4/5 · Rolling Stone 4.5/5 · The Guardian 5/5")
        self.assertEqual(ratings.sales_line(e), "Чарты и сертификаты: US #3 · UK #1 · UK Platinum · US 2× Platinum · JP 12,000")

    def test_grades_and_words(self):
        self.assertEqual(ratings.to10("A−"), 9)
        self.assertEqual(ratings.to10("3.5/5"), 7.0)
        self.assertIsNone(ratings.to10("favorable"))
        self.assertIsNone(ratings.to10("12/10"))
        self.assertEqual(ratings.to10("61%"), 6.1)
        s = ratings.summarize(ratings.parse("{{Album ratings|rev1=The Quietus|rev1score=Positive|rev2=Pitchfork|rev2score=7.8/10}}"))
        self.assertEqual([c["outlet"] for c in s["critics"]], ["Pitchfork"])
        self.assertEqual(s["critics_total"], 2)

    def test_newer_aggregate_fields(self):
        p = ratings.parse("{{Album ratings|aggregate1 = AnyDecentMusic?|aggregate1score = 7.9/10|MC=83/100|rev1=[[Clash (magazine)|Clash]]|rev1score=8/10}}")
        self.assertEqual((p["metacritic"], p["adm"]), (83, 7.9))
        self.assertEqual(p["critics"][0]["outlet"], "Clash")

    def test_clean_album(self):
        self.assertEqual(ratings.clean_album("Ceremony", "Ronhert Park ‡ REVIEW"), "Ronhert Park")
        self.assertEqual(ratings.clean_album("The Who", "Who's Next (CLASSIC REVIEW)"), "Who's Next")
        self.assertEqual(ratings.clean_album("Quakers", "Self-Titled"), "Quakers")
        self.assertIsNone(ratings.clean_album("Kanye West", '"Facts"'))
        self.assertEqual(ratings.norm("Travi$ Scott"), ratings.norm("Travis Scott"))

    def test_no_article_no_lines(self):
        self.assertEqual(ratings.card_line({"wp": None}), "")
        self.assertEqual(ratings.sales_line(None), "")


class ScheduleTest(unittest.TestCase):
    def test_due(self):
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        ago = lambda d: now - timedelta(days=d)
        self.assertTrue(ratings.due(None, ago(400), now))
        self.assertTrue(ratings.due({"checked": ago(1).isoformat()}, ago(5), now))
        self.assertFalse(ratings.due({"checked": ago(3).isoformat()}, ago(40), now))
        self.assertTrue(ratings.due({"checked": ago(8).isoformat()}, ago(40), now))
        self.assertFalse(ratings.due({"checked": ago(100).isoformat(), "wp": None}, ago(900), now))
        self.assertTrue(ratings.due({"checked": ago(100).isoformat(), "wp": "X"}, ago(900), now))

    def test_run_keeps_old_data_when_search_misses(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            pub = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            (data / "reviews.json").write_text(json.dumps([{"id": "a", "artist_name": "Charli XCX", "album": "Brat", "published": pub}]))
            old = {"checked": "2026-01-01T00:00:00+00:00", "wp": "Brat (album)", "metacritic": 95}
            (data / "ratings.json").write_text(json.dumps({"a": old}))
            with mock.patch.object(ratings, "DATA", data), mock.patch.object(ratings, "find_article", return_value=(None, None, None)), \
                    mock.patch.object(ratings.time, "sleep"):
                ratings.run()
            got = json.loads((data / "ratings.json").read_text())["a"]
            self.assertEqual(got["metacritic"], 95)
            self.assertNotEqual(got["checked"], old["checked"])

    def test_run_writes_entry(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            pub = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            (data / "archive.json").write_text(json.dumps([{"id": "a", "artist_name": "Charli XCX", "album": "Brat", "published": pub},
                                                          {"id": "b", "artist_name": "X", "album": '"Song"', "published": pub}]))
            with mock.patch.object(ratings, "DATA", data), mock.patch.object(ratings, "find_article", return_value=("Brat (album)", ARTICLE, 1)), \
                    mock.patch.object(ratings.time, "sleep"):
                ratings.run()
            got = json.loads((data / "ratings.json").read_text())
            self.assertEqual(got["a"]["wp_url"], "https://en.wikipedia.org/wiki/Brat_%28album%29")
            self.assertEqual(got["a"]["metacritic"], 95)
            self.assertIsNone(got["b"]["wp"])  # track review: not looked up


if __name__ == "__main__":
    unittest.main()
