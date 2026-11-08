"""Transcripts of archive reviews that are only a video (lmn/transcribe.py), and Luna's descriptions from them
(lmn/briefs.py)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lmn import briefs, gemini, llm, transcribe

SPOKEN = ("Hi everyone, Anthony Fantano here, the internet's busiest music nerd, and it's time for a review of the new "
          "Artist 1 album, Album 1. ") * 12


def arch(i, published, video=True, **kw):
    return {"id": f"{i:024x}", "artist_name": f"Artist {i}", "album": f"Album {i}", "published": published, "score": 7,
            "genres": ["noise rock"], **({"video_id": f"v{i}"} if video else {}), **kw}


def gemini_answer(text, finish="STOP"):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}]}


class Todo(unittest.TestCase):
    def test_only_retellings_with_a_video_and_no_transcript_newest_first(self):
        archive = [arch(1, "2012-01-01T00:00:00Z"), arch(2, "2015-01-01T00:00:00Z"), arch(3, "2013-01-01T00:00:00Z"),
                   arch(4, "2014-01-01T00:00:00Z", video=False), arch(5, "2016-01-01T00:00:00Z"), arch(6, "2011-01-01T00:00:00Z"),
                   arch(7, "2017-01-01T00:00:00Z")]
        data = {archive[0]["id"]: {"brief": "x", "src": "short"}, archive[1]["id"]: {"skip": "short", "short": "none"},
                archive[2]["id"]: {"brief": "x", "src": "short", "vf": transcribe.FAIL_MAX},
                archive[3]["id"]: {"brief": "x", "src": "short"}, archive[4]["id"]: {"brief": "full text one"},
                archive[5]["id"]: {"brief": "x", "src": "short"}, archive[6]["id"]: {"brief": "x", "src": "short"}}
        d = Path(tempfile.mkdtemp())
        (d / "notes.json").write_text(json.dumps({archive[3]["id"]: {"video_id": "from-notes"}}))
        with mock.patch.object(transcribe, "DATA", d):
            got = transcribe.todo(archive, data, {archive[6]["id"]})
        self.assertEqual([a["id"] for a in got], [archive[1]["id"], archive[3]["id"], archive[0]["id"], archive[5]["id"]])
        self.assertEqual(got[1]["video_id"], "from-notes")


class Ask(unittest.TestCase):
    a = {**arch(1, "2012-01-01T00:00:00Z"), "video_id": "abc"}

    def test_request_is_the_video_and_plain_text(self):
        with mock.patch.object(gemini, "generate", return_value=("m1", gemini_answer(SPOKEN))) as gen:
            self.assertEqual(transcribe.ask(self.a, "k"), ("ok", SPOKEN.strip(), "m1"))
        body = gen.call_args.args[0]
        self.assertEqual(body["contents"][0]["parts"][0], {"fileData": {"fileUri": "https://www.youtube.com/watch?v=abc"}})
        self.assertIn('"Artist 1 - Album 1"', body["contents"][0]["parts"][1]["text"])
        self.assertNotIn("responseMimeType", body["generationConfig"])
        self.assertEqual(gen.call_args.kwargs["budget"], gemini.VIDEO_BUDGET_SEC)

    def test_what_is_not_a_transcript(self):
        cases = [(gemini_answer("Too short."), "bad"), (gemini_answer(SPOKEN, "MAX_TOKENS"), "bad"),
                 (gemini_answer(SPOKEN.replace("Artist 1", "Someone").replace("Album 1", "Something")), "bad"),
                 ({"candidates": []}, "bad")]
        for raw, want in cases:
            with mock.patch.object(gemini, "generate", return_value=("m1", raw)):
                self.assertEqual(transcribe.ask(self.a, "k")[0], want)
        with mock.patch.object(gemini, "generate", return_value=(None, None)):
            self.assertEqual(transcribe.ask(self.a, "k"), ("none", None, None))


class Run(unittest.TestCase):
    def setUp(self):
        gemini._unavailable.clear()
        gemini.requests.clear()
        self.addCleanup(gemini._unavailable.clear)
        self.addCleanup(gemini.requests.clear)
        self.dir = Path(tempfile.mkdtemp())
        self.archive = [arch(i, f"20{10 + i:02d}-01-01T00:00:00Z") for i in range(1, 7)]
        self.data = {a["id"]: {"brief": "пересказ", "who": "кто", "src": "short"} for a in self.archive}
        (self.dir / "archive.json").write_text(json.dumps(self.archive))
        (self.dir / "briefs.json").write_text(json.dumps(self.data))

    def go(self, answers, lengths=None, env=None, models=("m1", "m2")):
        calls = []

        def gen(body, key, **kw):
            vid = body["contents"][0]["parts"][0]["fileData"]["fileUri"][-2:]
            calls.append(vid)
            a = answers(len(calls))
            model = next(m for m in models if m not in gemini._unavailable)
            gemini.requests[model] = gemini.requests.get(model, 0) + (2 if a is None else 1)  # no answer: a retry too
            if a is None:
                return None, None
            i = vid[1:]
            return model, gemini_answer(a.replace("Artist 1", f"Artist {i}").replace("Album 1", f"Album {i}"))
        lengths = lengths or {f"v{i}": 8 for i in range(1, 7)}
        with mock.patch.object(transcribe, "DATA", self.dir), mock.patch.object(briefs, "DATA", self.dir), \
                mock.patch.object(gemini, "MODELS", list(models)), mock.patch.object(gemini, "generate", side_effect=gen), \
                mock.patch.object(transcribe, "minutes", side_effect=lambda ids: {i: lengths[i] for i in ids if i in lengths}), \
                mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k", **(env or {})}), mock.patch("builtins.print"):
            transcribe.run()
        return calls, json.loads((self.dir / "briefs.json").read_text())

    def saved(self, i):
        p = self.dir / "transcripts" / f"{i:024x}.txt"
        return p.read_text() if p.exists() else None

    def test_writes_transcripts_newest_first(self):
        calls, data = self.go(lambda n: SPOKEN, env={"VIDEO_LIMIT": "2"})
        self.assertEqual(calls, ["v6", "v5"])
        self.assertIn("Artist 6 album, Album 6", self.saved(6))
        self.assertIsNone(self.saved(4))
        self.assertEqual(data, self.data)  # the retellings stay until Luna writes from the transcript

    def test_a_second_run_skips_what_is_done(self):
        self.go(lambda n: SPOKEN, env={"VIDEO_LIMIT": "2"})
        calls, _ = self.go(lambda n: SPOKEN, env={"VIDEO_LIMIT": "1"})
        self.assertEqual(calls, ["v4"])

    def test_keeps_the_days_share_of_video(self):
        with mock.patch.object(transcribe, "VIDEO_MINUTES", 20):
            calls, _ = self.go(lambda n: SPOKEN)
        self.assertEqual(len(calls), 2)  # 8 + 8 minutes; a third would pass 20

    def test_skips_long_and_missing_videos(self):
        lengths = {"v6": transcribe.MAX_VIDEO_MIN + 1, "v4": 5, "v3": 5, "v2": 5, "v1": 5}  # v5: gone
        calls, _ = self.go(lambda n: SPOKEN, lengths=lengths, env={"VIDEO_LIMIT": "1"})
        self.assertEqual(calls, ["v4"])

    def test_each_model_leaves_a_share_for_new_reviews(self):
        with mock.patch.object(transcribe, "PER_MODEL", 2):
            calls, _ = self.go(lambda n: SPOKEN)
        self.assertEqual(len(calls), 4)  # two on m1, two on m2, then every model's share is used

    def test_requests_without_an_answer_count_too(self):
        with mock.patch.object(transcribe, "PER_MODEL", 2):
            calls, _ = self.go(lambda n: None if n == 1 else SPOKEN)
        self.assertEqual(len(calls), 3)  # m1: two requests for no answer, so its share is gone; m2: two answers

    def test_no_answer_still_counts_its_minutes(self):
        with mock.patch.object(transcribe, "VIDEO_MINUTES", 20):
            calls, _ = self.go(lambda n: None if n == 1 else SPOKEN)
        self.assertEqual(len(calls), 2)

    def test_unusable_answer_counts_no_answer_stops(self):
        calls, data = self.go(lambda n: "Too short." if n == 1 else None)
        self.assertEqual(len(calls), 1 + transcribe.GIVE_UP)
        first = data[self.archive[5]["id"]]
        self.assertEqual((first["vf"], first["brief"], first["src"]), (1, "пересказ", "short"))
        self.assertNotIn("vf", data[self.archive[4]["id"]])  # no answer is not the video's fault


LUNA = {"brief": "Полное описание.", "about": "Длинно.", "who": "Группа; дебютный альбом.", "moods": [],
        "en": {"brief": "Full.", "about": "Long.", "who": "Band; debut album."}}


class BriefsFromTranscript(unittest.TestCase):
    """lmn/briefs.py: a retelling whose video has a transcript is written again, from the transcript, as a full one."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.archive = [arch(1, "2012-01-01T00:00:00Z"), arch(2, "2013-01-01T00:00:00Z"), arch(3, "2014-01-01T00:00:00Z")]
        (self.dir / "archive.json").write_text(json.dumps(self.archive))
        (self.dir / "transcripts").mkdir()
        for i in (1, 2):
            (self.dir / "transcripts" / f"{i:024x}.txt").write_text(f"What he says about album {i}. " * 40)
        self.data = {self.archive[0]["id"]: {"brief": "пересказ", "who": "кто", "src": "short", "p": 3, "tr": "m", "en": {"brief": "r"}},
                     self.archive[1]["id"]: {"skip": "short", "short": "none", "who": "кто", "p": 3},
                     self.archive[2]["id"]: {"brief": "пересказ", "src": "short", "p": 3, "tr": "m", "en": {"brief": "r"}}}
        (self.dir / "briefs.json").write_text(json.dumps(self.data))

    def go(self, answer):
        env = {"BRIEFS_LANG": "both", "BRIEFS_MINUTES": "5"}
        out = dict(gemini.parse_answer(json.dumps(answer, ensure_ascii=False)), model="m") if answer else None
        with mock.patch.object(briefs, "DATA", self.dir), mock.patch.dict(os.environ, env), \
                mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: "One line." for i in ids}), \
                mock.patch.object(llm, "summarize", return_value=out) as summ, \
                mock.patch.object(llm, "available", return_value=True), mock.patch("builtins.print"):
            briefs.run()
        return summ, json.loads((self.dir / "briefs.json").read_text())

    def test_written_again_from_the_transcript(self):
        summ, data = self.go(LUNA)
        self.assertEqual(len(summ.call_args_list), 2)  # the third has no transcript: its retelling stays
        for c in summ.call_args_list:
            self.assertIn("What he says about album", c.args[1])
            self.assertNotIn("short", c.kwargs)  # the full description's prompt, not the retelling's
        for i in (0, 1):
            e = data[self.archive[i]["id"]]
            self.assertEqual((e["brief"], e["src"], e["en"]["brief"], e.get("skip")), ("Полное описание.", "video", "Full.", None))
        self.assertEqual(data[self.archive[2]["id"]], self.data[self.archive[2]["id"]])
        self.assertTrue(briefs.finished(data[self.archive[0]["id"]], "both"))

    def test_a_failure_keeps_the_retelling_and_who(self):
        _, data = self.go(None)
        self.assertEqual(data[self.archive[0]["id"]]["brief"], "пересказ")
        none = data[self.archive[1]["id"]]
        self.assertEqual((none["who"], none["short"], none["fail"]), ("кто", "none", 1))

    def test_briefs_never_rewrites_one_from_a_transcript(self):
        self.assertTrue(briefs.finished({"brief": "x", "en": {"brief": "y"}, "tr": "m", "p": 1, "src": "video"}, "both"))


if __name__ == "__main__":
    unittest.main()
