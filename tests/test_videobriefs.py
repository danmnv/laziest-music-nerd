"""Full descriptions by the video for archive reviews that had only Fantano's short lines (lmn/videobriefs.py)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lmn import gemini, videobriefs

ANSWER = {"brief": "Шумный и злой дебют.", "about": "Длинно.", "who": "Группа из Ванкувера; дебютный альбом.",
          "moods": ["когда злишься"], "en": {"brief": "A loud debut.", "about": "Long.", "who": "Vancouver band; debut album."}}


def arch(i, published, video=True, **kw):
    return {"id": f"{i:024x}", "artist_name": f"Artist {i}", "album": f"Album {i}", "published": published, "score": 7,
            "genres": ["noise rock"], **({"video_id": f"v{i}"} if video else {}), **kw}


def answer(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj, ensure_ascii=False)}]}}]}


class Todo(unittest.TestCase):
    def test_only_retellings_with_a_video_newest_first(self):
        archive = [arch(1, "2012-01-01T00:00:00Z"), arch(2, "2015-01-01T00:00:00Z"), arch(3, "2013-01-01T00:00:00Z"),
                   arch(4, "2014-01-01T00:00:00Z", video=False), arch(5, "2016-01-01T00:00:00Z"), arch(6, "2011-01-01T00:00:00Z")]
        data = {archive[0]["id"]: {"brief": "x", "src": "short"}, archive[1]["id"]: {"skip": "short", "short": "none"},
                archive[2]["id"]: {"brief": "x", "src": "short", "vf": videobriefs.FAIL_MAX},
                archive[3]["id"]: {"brief": "x", "src": "short"}, archive[4]["id"]: {"brief": "full text one"},
                archive[5]["id"]: {"brief": "x", "src": "short"}}
        notes = {archive[3]["id"]: {"video_id": "from-notes"}}
        got = videobriefs.todo(archive, data, notes)
        self.assertEqual([a["id"] for a in got], [archive[1]["id"], archive[3]["id"], archive[0]["id"], archive[5]["id"]])
        self.assertEqual(got[1]["video_id"], "from-notes")


class Prompt(unittest.TestCase):
    def test_archive_rules_by_the_video(self):
        self.assertIn("Выше — сам его видеообзор на YouTube", videobriefs.PROMPT)
        self.assertNotIn("Ниже — текст его обзора на английском", videobriefs.PROMPT)
        self.assertIn(gemini._WHO_RU, videobriefs.PROMPT)
        self.assertIn(gemini._STYLE_RU, videobriefs.PROMPT)

    def test_request_has_the_video_lines_tags_and_english(self):
        a = {**arch(1, "2012-01-01T00:00:00Z"), "video_id": "abc"}
        note = {"blurb": "A loud one.", "fav": [{"t": "SONG A"}, {"t": "SONG B"}]}
        with mock.patch.object(gemini, "generate", return_value=("m1", answer(ANSWER))) as gen:
            got, out = videobriefs.ask(a, note, "k")
        self.assertEqual((got, out["model"]), ("ok", "m1"))
        body = gen.call_args.args[0]
        self.assertEqual(body["contents"][0]["parts"][0], {"fileData": {"fileUri": "https://www.youtube.com/watch?v=abc"}})
        text = body["contents"][0]["parts"][1]["text"]
        for s in ("Строки под видео:\nA loud one.\nFAV TRACKS: SONG A, SONG B", "Теги: noise rock.", '"en": объект',
                  "Fantano's score: 7/10", "Заголовок: Artist 1 - Album 1"):
            self.assertIn(s, text)
        self.assertEqual(gen.call_args.kwargs["budget"], gemini.VIDEO_BUDGET_SEC)

    def test_no_answer_and_empty_answer_differ(self):
        a = {**arch(1, "2012-01-01T00:00:00Z"), "video_id": "abc"}
        with mock.patch.object(gemini, "generate", return_value=(None, None)):
            self.assertEqual(videobriefs.ask(a, {}, "k"), ("none", None))
        with mock.patch.object(gemini, "generate", return_value=("m1", answer({**ANSWER, "brief": ""}))):
            self.assertEqual(videobriefs.ask(a, {}, "k")[0], "bad")
        with mock.patch.object(gemini, "generate", return_value=("m1", {"candidates": []})):
            self.assertEqual(videobriefs.ask(a, {}, "k"), ("bad", {"model": "m1"}))


class Run(unittest.TestCase):
    def setUp(self):
        gemini._unavailable.clear()
        self.addCleanup(gemini._unavailable.clear)
        self.dir = Path(tempfile.mkdtemp())
        self.archive = [arch(i, f"20{10 + i:02d}-01-01T00:00:00Z") for i in range(1, 7)]
        self.data = {a["id"]: {"brief": "пересказ", "who": "кто", "src": "short"} for a in self.archive}
        (self.dir / "archive.json").write_text(json.dumps(self.archive))
        (self.dir / "briefs.json").write_text(json.dumps(self.data))
        (self.dir / "notes.json").write_text("{}")

    def go(self, answers, lengths=None, env=None, models=("m1", "m2")):
        calls = []

        def gen(body, key, **kw):
            calls.append(body["contents"][0]["parts"][0]["fileData"]["fileUri"][-2:])
            a = answers(len(calls))
            if a is None:
                return None, None
            model = next(m for m in models if m not in gemini._unavailable)
            return model, answer(a)
        lengths = lengths or {f"v{i}": 8 for i in range(1, 7)}
        with mock.patch.object(videobriefs, "DATA", self.dir), mock.patch.object(gemini, "MODELS", list(models)), \
                mock.patch.object(gemini, "generate", side_effect=gen), \
                mock.patch.object(videobriefs, "minutes", side_effect=lambda ids: {i: lengths[i] for i in ids if i in lengths}), \
                mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k", **(env or {})}), mock.patch("builtins.print"):
            videobriefs.run()
        return calls, json.loads((self.dir / "briefs.json").read_text())

    def test_writes_full_descriptions_newest_first(self):
        calls, data = self.go(lambda n: ANSWER, env={"VIDEO_LIMIT": "2"})
        self.assertEqual(calls, ["v6", "v5"])
        e = data[self.archive[5]["id"]]
        self.assertEqual((e["src"], e["brief"], e["en"]["brief"], e["p"]), ("video", ANSWER["brief"], "A loud debut.", 3))
        self.assertEqual(data[self.archive[0]["id"]]["src"], "short")

    def test_keeps_the_days_share_of_video(self):
        with mock.patch.object(videobriefs, "VIDEO_MINUTES", 20):
            calls, _ = self.go(lambda n: ANSWER)
        self.assertEqual(len(calls), 2)  # 8 + 8 minutes; a third would pass 20

    def test_skips_long_and_missing_videos(self):
        lengths = {"v6": videobriefs.MAX_VIDEO_MIN + 1, "v4": 5, "v3": 5, "v2": 5, "v1": 5}  # v5: gone
        calls, data = self.go(lambda n: ANSWER, lengths=lengths, env={"VIDEO_LIMIT": "1"})
        self.assertEqual(calls, ["v4"])
        self.assertEqual(data[self.archive[5]["id"]]["src"], "short")

    def test_each_model_leaves_a_share_for_new_reviews(self):
        with mock.patch.object(videobriefs, "PER_MODEL", 2):
            calls, _ = self.go(lambda n: ANSWER)
        self.assertEqual(len(calls), 4)  # two on m1, two on m2, then every model's share is used

    def test_empty_answer_counts_no_answer_stops(self):
        calls, data = self.go(lambda n: {**ANSWER, "brief": ""} if n == 1 else None)
        self.assertEqual(len(calls), 1 + videobriefs.GIVE_UP)
        first = data[self.archive[5]["id"]]
        self.assertEqual((first["vf"], first["brief"], first["src"]), (1, "пересказ", "short"))
        self.assertNotIn("vf", data[self.archive[4]["id"]])  # no answer is not the video's fault

    def test_short_none_gets_a_description(self):
        self.data[self.archive[5]["id"]] = {"skip": "short", "short": "none", "who": "кто"}
        (self.dir / "briefs.json").write_text(json.dumps(self.data))
        _, data = self.go(lambda n: ANSWER, env={"VIDEO_LIMIT": "1"})
        e = data[self.archive[5]["id"]]
        self.assertEqual((e.get("skip"), e.get("short"), e["src"]), (None, None, "video"))


if __name__ == "__main__":
    unittest.main()
