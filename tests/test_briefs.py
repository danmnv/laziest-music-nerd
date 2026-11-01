import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lmn import briefs, gemini, http, llm, site

ANSWER = {"brief": "Коротко.", "about": "Длинно. " * 100, "who": "Группа из Оксфорда.", "moods": ["для работы за столом", "не то"],
          "best_tracks": [], "artist": "Radiohead", "album": "Kid A", "score_note": ""}


def chat(answer):
    return {"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]}


class ParseAnswer(unittest.TestCase):
    def test_about_is_cut_at_a_sentence(self):
        out = gemini.parse_answer(json.dumps(ANSWER))
        self.assertLessEqual(len(out["about"]), gemini.ABOUT_MAX)
        self.assertTrue(out["about"].endswith("."))
        self.assertEqual(out["moods"], ["для работы за столом"])


class Providers(unittest.TestCase):
    def setUp(self):
        llm._dead.clear()
        llm._last.clear()

    def test_falls_back_to_the_next_provider_and_skips_missing_keys(self):
        calls = []

        def fake(url, **kw):
            calls.append((url, kw["headers"]["Authorization"]))
            if "mistral" in url:
                raise http.HttpError(401, '{"message":"Unauthorized"}', url)
            return chat(ANSWER)

        env = {"MISTRAL_API_KEY": "m", "GROQ_API_KEY": "", "CEREBRAS_API_KEY": "c"}
        with mock.patch.dict(os.environ, env), mock.patch.object(http, "get_json", side_effect=fake):
            out = llm.summarize("Radiohead - Kid A", "text " * 200, sleep=lambda s: None)
            self.assertEqual(out["model"], "llama-3.3-70b")
            self.assertEqual([u.split("/")[2] for u, _ in calls], ["api.mistral.ai", "api.cerebras.ai"])
            self.assertEqual(calls[1][1], "Bearer c")
            calls.clear()
            llm.summarize("Radiohead - Kid A", "text " * 200, sleep=lambda s: None)  # a wrong key is not tried again
            self.assertEqual([u.split("/")[2] for u, _ in calls], ["api.cerebras.ai"])

    def test_no_keys_no_calls(self):
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "", "GROQ_API_KEY": "", "CEREBRAS_API_KEY": ""}), \
                mock.patch.object(http, "get_json") as g:
            self.assertIsNone(llm.summarize("A - B", "text"))
            g.assert_not_called()


class Run(unittest.TestCase):
    def test_targets_and_saved_file(self):
        archive = [
            {"id": "a" * 24, "artist_name": "Radiohead", "album": "Kid A", "published": "2020-01-01", "score": 10},
            {"id": "b" * 24, "artist_name": "X", "album": "Y", "published": "2021-01-01", "guest": True},
            {"id": "c" * 24, "artist_name": "Kanye West", "album": '"Facts"', "published": "2021-01-02"},
            {"id": "d" * 24, "artist_name": "HMLTD", "album": "FANGS", "published": "2022-01-01"},
            {"id": "YGFqOLufncA", "artist_name": "Z", "album": "W", "published": "2026-01-01"},
            {"id": "e" * 24, "artist_name": "Short", "album": "Text", "published": "2019-01-01"}]
        reviews = [{"id": "d" * 24, "ai": {"brief": "уже есть"}}]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(archive))
            (p / "reviews.json").write_text(json.dumps(reviews))
            texts = {"a" * 24: "long text " * 100, "e" * 24: "too short"}
            with mock.patch.object(briefs, "DATA", p), \
                    mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: texts.get(i, "") for i in ids}) as ft, \
                    mock.patch.object(briefs.llm, "summarize", return_value=dict(gemini.parse_answer(json.dumps(ANSWER)), model="m")) as s:
                briefs.run()
            self.assertEqual(ft.call_args[0][0], ["a" * 24, "e" * 24])  # no guest, song, done or YouTube-only review
            self.assertEqual(s.call_count, 1)
            out = json.loads((p / "briefs.json").read_text())
            self.assertEqual(set(out), {"a" * 24})
            self.assertEqual(out["a" * 24]["brief"], "Коротко.")
            self.assertEqual(out["a" * 24]["m"], "m")


class Site(unittest.TestCase):
    A = {"id": "a" * 24, "url": "https://theneedledrop.com/x", "published": "2020-01-01", "artist_name": "Radiohead",
         "album": "Kid A", "score": 10}

    def test_archive_page_shows_the_long_brief_and_hides_the_quote(self):
        html = site.archive_page(self.A, [self.A], note={"blurb": "Fantano's line."},
                                 brief={"brief": "Коротко.", "about": "Длинно и подробно.", "who": "Группа из Оксфорда."})
        self.assertIn("<dt>Кто</dt><dd>Группа из Оксфорда.</dd><dt>Бриф</dt><dd>Длинно и подробно.</dd>", html)
        self.assertNotIn("Fantano&#x27;s line", html)
        self.assertNotIn("Коротко.", html)

    def test_release_page_without_a_card_brief_takes_the_archive_one(self):
        r = dict(self.A, genres=[], ai={"brief": None, "who": "Своё."})
        html = site.release_page(r, brief={"brief": "Коротко.", "about": "Длинно.", "who": "Чужое."})
        self.assertIn("<dd>Длинно.</dd>", html)
        self.assertIn("Своё.", html)
        self.assertNotIn("Чужое.", html)


if __name__ == "__main__":
    unittest.main()
