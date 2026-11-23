import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lmn import decade_tens, gemini, site, transcribe
from tests.test_transcribe import gemini_answer


VID = "erqGhrVB5Ao"
ALBUMS = decade_tens.EPISODES[VID][2]
BRIEF = "Разбирает, как яркие мелодии сочетаются со свободной импровизацией."
ABOUT = "Подчёркивает, как музыканты меняют динамику и переходят от мелодии к свободной импровизации."
EXISTING = {
    "id": "original-zappa", "artist_name": "Frank Zappa", "album": "Hot Rats", "classic": True,
    "url": "https://theneedledrop.com/classic", "published": "2015-01-01T00:00:00Z",
}


def response_rows():
    return [{"id": key, "artist": artist, "album": title, "start_seconds": 30 + 50 * i,
             "brief": BRIEF, "about": ABOUT}
            for i, (key, artist, title, _) in enumerate(ALBUMS)]


class DecadeTensTest(unittest.TestCase):
    def test_archive_keeps_existing_record_and_adds_only_missing_albums(self):
        archive = [EXISTING.copy()]
        self.assertEqual(decade_tens.add_to_archive(archive), 24)
        self.assertEqual(decade_tens.add_to_archive(archive), 0)
        self.assertEqual(archive[0], EXISTING)
        self.assertEqual(len({a["id"] for a in archive}), 25)
        self.assertTrue(all(a["score"] == 10 and "video_id" not in a for a in archive[1:]))

    def test_response_is_per_album_with_distinct_timestamps(self):
        rows = response_rows()
        parsed = decade_tens.parse_answer(gemini_answer(json.dumps({"items": rows})), ALBUMS, 481)
        self.assertEqual(parsed["black-saint"]["start_seconds"], 130)
        self.assertEqual(parsed["black-saint"]["brief"], BRIEF)
        rows[1]["start_seconds"] = rows[0]["start_seconds"]
        with self.assertRaisesRegex(ValueError, "same timestamp"):
            decade_tens.parse_answer(gemini_answer(json.dumps({"items": rows})), ALBUMS, 481)

    def test_rejection_log_distinguishes_truncated_response_and_invalid_json(self):
        cases = [(gemini_answer("{}", "MAX_TOKENS"), "generation ended with 'MAX_TOKENS'"),
                 (gemini_answer("{"), "invalid JSON at line 1, column 2")]
        for raw, detail in cases:
            with self.subTest(detail=detail), mock.patch.object(gemini, "generate", return_value=("test-model", raw)), \
                    mock.patch("builtins.print") as printed:
                self.assertIsNone(decade_tens.request(VID, "fake-key", 8))
                self.assertIn(detail, printed.call_args.args[0])

    def test_priority_pass_reserves_quota_and_reuses_a_cached_episode(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            def generate(body, api_key, **kwargs):
                self.assertIn(VID, body["contents"][0]["parts"][0]["fileData"]["fileUri"])
                self.assertTrue(kwargs["before_request"]("test-model", float("inf")))
                gemini.requests["test-model"] += 1
                return "test-model", gemini_answer(json.dumps({"items": response_rows()}))

            with mock.patch.object(transcribe, "DATA", data), mock.patch.object(transcribe, "minutes", return_value={VID: 8}), \
                    mock.patch.object(transcribe.notes, "albums", return_value={}), mock.patch.object(gemini, "requests", {"test-model": 0}), \
                    mock.patch.object(gemini, "generate", side_effect=generate) as mock_generate:
                budget = transcribe.RunBudget({"minutes": 10, "requests": {"test-model": 1}})
                self.assertEqual(transcribe.process_decade_tens([EXISTING], "fake-key", budget, 0), 1)
                self.assertEqual(budget.minutes_left, 2)
                self.assertEqual(transcribe.process_decade_tens([EXISTING], "fake-key", budget, 0), 0)
                mock_generate.assert_called_once()

    def test_site_keeps_original_review_as_the_source_and_uses_episode_text_for_new_cards(self):
        with tempfile.TemporaryDirectory() as d:
            data, out = Path(d, "data"), Path(d, "out")
            data.mkdir()
            dylan = {"id": "original-dylan", "artist_name": "Bob Dylan", "album": "Highway 61 Revisited",
                     "classic": True, "url": "https://theneedledrop.com/dylan", "published": "2015-01-02T00:00:00Z"}
            (data / "archive.json").write_text(json.dumps([EXISTING, dylan]))
            original_brief = "Существующий пересказ отдельного обзора."
            original_about = "Текст из отдельного обзора, в котором подробно разбирается музыка."
            (data / "briefs.json").write_text(json.dumps({
                EXISTING["id"]: {"brief": original_brief, "about": original_about, "src": "video"},
            }))
            items = decade_tens.parse_answer(gemini_answer(json.dumps({"items": response_rows()})), ALBUMS, 481)
            cover = {"cv": "https://example.com/cover.jpg", "t": [["Track One", 190]], "y": "1963"}
            decade_tens.save(data / decade_tens.FILENAME, {"videos": {VID: {"items": items}}, "albums": {"black-saint": cover}})
            with mock.patch.object(site, "DATA", data), mock.patch.object(site, "OUT", out):
                site.build()
            self.assertFalse((out / "r" / "ten-hot-rats.html").exists())
            for review_id, brief, about, seconds in (
                ("original-zappa", original_brief, original_about, 30),
                ("original-dylan", None, None, 80),
                ("ten-black-saint", BRIEF, ABOUT, 130),
            ):
                page = (out / "r" / f"{review_id}.html").read_text()
                link = decade_tens.video_url(VID, seconds)
                self.assertEqual(page.count(f'href="{link}"'), 1)
                self.assertRegex(page, rf'<p><a class="score green" href="{re.escape(link)}"[^>]*>10/10</a>')
                payload = json.loads((out / "rt" / f"{review_id}.json").read_text())
                self.assertEqual(payload.get("brief"), brief)
                self.assertEqual(payload["series"]["url"], link)
                if about:
                    self.assertIn(about, page)
                if review_id.startswith("original-"):
                    self.assertNotIn(ABOUT, page)
                    self.assertRegex(page, r'10/10</a> <span class="score green">CLASSIC</span>')
            page = (out / "r" / "ten-black-saint.html").read_text()
            self.assertIn("10/10", page)
            self.assertIn(cover["cv"], page)
            self.assertIn("Track One", page)


class StandaloneTensTest(unittest.TestCase):
    def test_tens_with_thin_or_missing_text_precede_newer_regular_reviews(self):
        regular = {"id": "regular", "published": "2025-01-01", "score": 8, "video_id": "regular",
                   "artist_name": "Other", "album": "An album"}
        kids = {"id": "kids", "published": "2018-06-11", "score": 10, "artist_name": "Kids See Ghosts",
                "album": "KIDS SEE GHOSTS", "video_id": "9rkFbKVownA"}
        madvillain = {"id": "6684c32c49ea2a054e091603", "published": "2013-01-01",
                      "artist_name": "Madvillainy", "album": "Madvillain", "classic": True}
        hounds = {"id": "6684c32c49ea2a054e091d7a", "published": "2015-05-01", "artist_name": "Kate Bush",
                  "album": "Hounds of Love", "classic": True}
        archive = [regular, kids, {**EXISTING, "video_id": "zappa"}, madvillain, hounds,
                   {**kids, "id": "no-brief", "published": "2017-01-01", "album": "Another album"},
                   {**kids, "id": "complete", "album": "Full text"}]
        data = {"regular": {"src": "short"}, "kids": {"src": "short", "brief": "Одна фраза."},
                "complete": {"brief": BRIEF, "about": ABOUT, "src": "video"}}
        notes = {hounds["id"]: {"video_id": "wuE3plpz5Ho"}}
        with mock.patch.object(transcribe, "_load", side_effect=lambda name, default: notes if name == "notes.json" else default):
            items = transcribe.todo(archive, data, set())
        self.assertEqual([a["id"] for a in items], ["kids", "no-brief", hounds["id"], EXISTING["id"], madvillain["id"], "regular"])
        self.assertEqual(items[2]["video_id"], "wuE3plpz5Ho")
        self.assertEqual(items[-2]["video_id"], "u7JPMQkVuMo")

    def test_video_only_ten_gets_a_brief_before_the_regular_archive(self):
        from lmn import briefs

        standalone = {"id": "9rkFbKVownA", "published": "2018-06-11", "score": 10,
                      "artist_name": "Kids See Ghosts", "album": "KIDS SEE GHOSTS"}
        ordinary = {"id": "a" * 24, "published": "2025-01-01", "score": 7,
                    "artist_name": "Other", "album": "Other album"}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps([ordinary, standalone]))
            (p / "transcripts").mkdir()
            (p / "transcripts" / (standalone["id"] + ".txt")).write_text("A complete review in test data. " * 30)
            with mock.patch.object(briefs, "DATA", p), \
                    mock.patch.dict("os.environ", {"BRIEFS_LANG": "both", "BRIEFS_LIMIT": "1"}), \
                    mock.patch.object(briefs.tnd, "fetch_texts", side_effect=TimeoutError) as fetch, \
                    mock.patch.object(briefs.llm, "available", return_value=True), \
                    mock.patch.object(briefs.llm, "summarize", return_value={"brief": BRIEF, "about": ABOUT}) as ask:
                briefs.run()
            fetch.assert_called_once_with([ordinary["id"]])
            self.assertEqual(ask.call_args.args[0], "Kids See Ghosts - KIDS SEE GHOSTS")
            saved = json.loads((p / "briefs.json").read_text())
            self.assertEqual(saved[standalone["id"]]["about"], ABOUT)
            self.assertEqual(saved[standalone["id"]]["src"], "video")
