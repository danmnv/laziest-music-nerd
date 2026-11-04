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
        self.assertEqual(out["moods"], ["фоном для работы"])  # an old word, merged (owner, 2026-11-02)

    def test_a_long_card_brief_keeps_whole_sentences_only_if_fantanos_view_stays(self):
        long_ = dict(ANSWER, brief="Новый альбом группы, где она пробует синт-фанк и поп. Фантано считает запись интересной. " + "Ещё слова. " * 20)
        out = gemini.parse_answer(json.dumps(long_))["brief"]
        self.assertLessEqual(len(out), gemini.BRIEF_MAX)
        self.assertTrue(out.startswith("Новый альбом группы, где она пробует синт-фанк и поп. Фантано считает запись интересной."))
        self.assertTrue(out.endswith("."))
        one = dict(ANSWER, brief="Новый альбом " + "очень " * 40 + "длинный; Фантано доволен.")
        self.assertEqual(gemini.parse_answer(json.dumps(one))["brief"], one["brief"])  # cutting would lose his view

    def test_a_long_three_sentence_brief_is_cut_to_two_even_without_fantanos_name(self):
        three = "Звучание плотное и шумное, с синтами на первом плане. " + "Мелодии цепкие, припевы запоминаются сразу, а продакшн богатый. " + "Но вокал тонет в миксе, а вторая половина альбома заметно провисает и повторяет первую."
        three += " Ещё одно длинное предложение, которое уже точно не помещается в карточку, даже если она стала заметно длиннее, чем была раньше."
        self.assertGreater(len(three), gemini.BRIEF_MAX)
        out = gemini.parse_answer(json.dumps(dict(ANSWER, brief=three)))["brief"]
        self.assertLessEqual(len(out), gemini.BRIEF_MAX)
        self.assertTrue(out.startswith("Звучание плотное") and out.endswith(".") and out.count(". ") >= 1)

    def test_a_dangling_semicolon_in_who_becomes_a_full_stop(self):
        out = gemini.parse_answer(json.dumps(dict(ANSWER, who="Американская певица и композитор; ", en={"who": "American singer;"})))
        self.assertEqual((out["who"], out["en"]["who"]), ("Американская певица и композитор.", "American singer."))
        self.assertEqual(gemini.tidy_who("Рэпер из Атланты; третий альбом."), "Рэпер из Атланты; третий альбом.")
        self.assertIsNone(gemini.tidy_who(" "))

    def test_moods_are_the_same_list_as_the_bots(self):
        import re
        js = (Path(__file__).parent.parent / "worker/src/index.js").read_text()
        block = re.search(r"const MOODS = \[(.*?)\];", js, re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', block), gemini.MOODS)

    def test_vibes_are_the_same_in_the_bot_and_on_the_site(self):
        import re
        root = Path(__file__).parent.parent
        self.assertTrue(set(gemini.VIBES) <= set(gemini.MOODS) and set(gemini.MOOD_ALIAS.values()) <= set(gemini.VIBES))
        self.assertEqual(gemini.shown_moods(["фоном", "для работы за столом", "ночью", "в дорогу", "для бодрости"]),
                         ["фоном для работы", "в дорогу"])  # merged, retired, no repeats (owner, 2026-11-02)
        for f in ("worker/src/index.js", "site_src/app.js"):
            block = re.search(r"const VIBES = \{(.*?)\};", (root / f).read_text(), re.S).group(1)
            self.assertEqual(dict(re.findall(r'"([^"]+)": "([^"]+)"', block)), gemini.VIBES, f)
            alias = re.search(r"const MOOD_ALIAS = \{(.*?)\};", (root / f).read_text(), re.S).group(1)
            self.assertEqual(dict(re.findall(r'"([^"]+)": "([^"]+)"', alias)), gemini.MOOD_ALIAS, f)


class Translate(unittest.TestCase):
    def test_one_request_for_all_and_the_same_order(self):
        en = [{"brief": "A good one.", "about": "Long.", "who": "A band."}, {"brief": "A bad one.", "about": "", "who": ""}]
        ru = [{"brief": "Хороший.", "about": "Длинно.", "who": "Группа."}, {"brief": "Плохой.", "about": "", "who": ""}]
        answer = {"candidates": [{"content": {"parts": [{"text": json.dumps(ru, ensure_ascii=False)}]}}]}
        with mock.patch.object(gemini, "generate", return_value=("gemini-3.5-flash", answer)) as g:
            out = gemini.translate(en, api_key="k")
        self.assertEqual(g.call_count, 1)
        self.assertIn('"A bad one."', g.call_args.args[0]["contents"][0]["parts"][0]["text"])
        self.assertEqual([x["brief"] for x in out], ["Хороший.", "Плохой."])
        self.assertEqual(out[0]["tr"], "gemini-3.5-flash")
        short = {"candidates": [{"content": {"parts": [{"text": json.dumps(ru[:1])}]}}]}
        with mock.patch.object(gemini, "generate", return_value=("m", short)):
            self.assertIsNone(gemini.translate(en, api_key="k"))  # a lost item would shift every brief after it

    def test_english_prompt_for_groq(self):
        seen = []

        def fake(url, **kw):
            seen.append(kw["json_body"]["messages"][0]["content"])
            return chat(ANSWER)

        llm._dead.clear()
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "g"}), mock.patch.object(http, "get_json", side_effect=fake):
            llm.ask("groq", "A - B", "text", lang="en", sleep=lambda s: None)
        self.assertTrue(seen[0].startswith("You help run"))
        self.assertIn("в наушниках, вдумчиво", seen[0])  # moods still from the Russian list


class Providers(unittest.TestCase):
    def setUp(self):
        llm._dead.clear()
        llm._spent.clear()
        llm._last.clear()

    def test_groq_moves_to_its_next_model_when_the_day_is_used_up(self):
        calls = []
        day = '{"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` on tokens per day (TPD): Limit 200000"}}'

        def fake(url, **kw):
            calls.append(kw["json_body"]["model"])
            if kw["json_body"]["model"] == "openai/gpt-oss-120b":
                raise http.HttpError(429, day, url)
            return chat(ANSWER)

        llm._picked["groq"] = "openai/gpt-oss-120b"
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "", "GROQ_API_KEY": "g"}), \
                mock.patch.object(http, "get_json", side_effect=fake):
            out = llm.summarize("A - B", "text", sleep=lambda s: None)
            llm.summarize("A - C", "text", sleep=lambda s: None)
            self.assertTrue(llm.available())
        llm._picked.clear()
        self.assertEqual(out["model"], "qwen/qwen3.8-27b")
        # the day's limit is not waited out (no retries), and the spent model isn't asked again
        self.assertEqual(calls, ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "qwen/qwen3.8-27b"])

    def test_when_every_groq_model_is_spent_the_provider_is_done(self):
        day = '{"error":{"message":"tokens per day (TPD)"}}'
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "", "GROQ_API_KEY": "g"}), \
                mock.patch.object(http, "get_json", side_effect=http.HttpError(429, day, "u")) as g:
            self.assertIsNone(llm.summarize("A - B", "text", sleep=lambda s: None))
            self.assertFalse(llm.available())
        self.assertEqual(g.call_count, 2)  # the default model and qwen, once each

    def test_a_renamed_extra_model_is_dropped_alone(self):
        calls = []

        def fake(url, **kw):
            calls.append(kw["json_body"]["model"])
            if kw["json_body"]["model"] == "qwen/qwen3.8-27b":
                raise http.HttpError(404, '{"error":{"code":"model_not_found"}}', url)
            raise http.HttpError(429, '{"error":{"message":"tokens per day (TPD)"}}', url)

        llm._picked["groq"] = "openai/gpt-oss-120b"
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "", "GROQ_API_KEY": "g"}), \
                mock.patch.object(http, "get_json", side_effect=fake):
            self.assertIsNone(llm.summarize("A - B", "text", sleep=lambda s: None))
        self.assertEqual(llm._picked["groq"], "openai/gpt-oss-120b")  # the default's pick stays
        llm._picked.clear()
        self.assertEqual(calls, ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"])

    def test_falls_back_to_the_next_provider(self):
        calls = []

        def fake(url, **kw):
            calls.append((url, kw["headers"]["Authorization"]))
            if "mistral" in url:
                raise http.HttpError(401, '{"message":"Unauthorized"}', url)
            return chat(ANSWER)

        llm._picked.clear()
        env = {"MISTRAL_API_KEY": "m", "GROQ_API_KEY": "g"}
        with mock.patch.dict(os.environ, env), mock.patch.object(http, "get_json", side_effect=fake):
            out = llm.summarize("Radiohead - Kid A", "text " * 200, sleep=lambda s: None)
            self.assertEqual(out["model"], "llama-3.3-70b-versatile")
            self.assertEqual([u.split("/")[2] for u, _ in calls], ["api.mistral.ai", "api.groq.com"])
            self.assertEqual(calls[1][1], "Bearer g")
            calls.clear()
            llm.summarize("Radiohead - Kid A", "text " * 200, sleep=lambda s: None)  # a wrong key is not tried again
            self.assertEqual([u.split("/")[2] for u, _ in calls], ["api.groq.com"])

    def test_a_provider_still_limited_after_retries_is_left_for_the_run(self):
        calls = []

        def fake(url, **kw):
            calls.append(url.split("/")[2])
            if "mistral" in url:
                raise http.HttpError(429, '{"message":"Requests rate limit exceeded"}', url)
            return chat(ANSWER)

        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "m", "GROQ_API_KEY": "g"}), \
                mock.patch.object(http, "get_json", side_effect=fake):
            llm.summarize("A - B", "text", sleep=lambda s: None)
            llm.summarize("A - C", "text", sleep=lambda s: None)
        self.assertEqual(calls, ["api.mistral.ai"] * 3 + ["api.groq.com", "api.groq.com"])

    def test_a_retired_model_is_replaced_from_the_models_list(self):
        llm._picked.clear()
        calls = []

        def fake(url, **kw):
            calls.append((url.split("/")[-1], (kw.get("json_body") or {}).get("model")))
            if url.endswith("/models"):
                return {"data": [{"id": "whisper-large-v3"}, {"id": "qwen/qwen3-32b"}]}
            if kw["json_body"]["model"] == "llama-3.3-70b-versatile":
                raise http.HttpError(404, '{"error":{"code":"model_not_found"}}', url)
            return chat(ANSWER)

        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "", "GROQ_API_KEY": "g"}), \
                mock.patch.object(http, "get_json", side_effect=fake):
            out = llm.summarize("A - B", "text", sleep=lambda s: None)
            self.assertEqual(out["model"], "qwen/qwen3-32b")
            llm.summarize("A - C", "text", sleep=lambda s: None)
        self.assertEqual(calls, [("completions", "llama-3.3-70b-versatile"), ("models", None), ("completions", "qwen/qwen3-32b"),
                                 ("completions", "qwen/qwen3-32b")])
        llm._picked.clear()

    def test_no_keys_no_calls(self):
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "", "GROQ_API_KEY": ""}), \
                mock.patch.object(http, "get_json") as g:
            self.assertIsNone(llm.summarize("A - B", "text"))
            g.assert_not_called()


class Run(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"BRIEFS_LANG": "ru"})
        env.start()
        self.addCleanup(env.stop)

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
                    mock.patch.object(briefs.llm, "available", return_value=True), \
                    mock.patch.object(briefs.llm, "summarize", return_value=dict(gemini.parse_answer(json.dumps(ANSWER)), model="m")) as s:
                briefs.run()
            self.assertEqual(ft.call_args[0][0], ["a" * 24, "e" * 24])  # no guest, song, done or YouTube-only review
            self.assertEqual(s.call_count, 1)
            out = json.loads((p / "briefs.json").read_text())
            self.assertEqual(out["e" * 24], {"skip": "short"})  # not fetched again next run
            self.assertEqual(out["a" * 24]["brief"], "Коротко.")
            self.assertEqual(out["a" * 24]["m"], "m")

    def test_skipped_and_failed_ones_dont_block_the_limit(self):
        archive = [{"id": c * 24, "artist_name": c, "album": c, "published": f"2020-01-0{i + 1}"} for i, c in enumerate("abcd")]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(archive))
            (p / "briefs.json").write_text(json.dumps({"d" * 24: {"fail": 1}}))
            texts = {"d" * 24: "x " * 300, "c" * 24: "", "b" * 24: "y " * 300, "a" * 24: "z " * 300}
            answers = [None, dict(ANSWER, model="m")]  # d fails again, b gets one; the limit is 2 tries
            with mock.patch.object(briefs, "DATA", p), mock.patch.dict(os.environ, {"BRIEFS_LIMIT": "2"}), \
                    mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: texts[i] for i in ids}), \
                    mock.patch.object(briefs.llm, "available", return_value=True), \
                    mock.patch.object(briefs.llm, "summarize", side_effect=answers):
                briefs.run()
            out = json.loads((p / "briefs.json").read_text())
            self.assertEqual(out["d" * 24], {"fail": 2})
            self.assertEqual(out["c" * 24], {"skip": "no text"})
            self.assertEqual(out["b" * 24]["brief"], "Коротко.")
            self.assertNotIn("a" * 24, out)
            self.assertTrue(all(briefs.finished(out[k]) for k in ("d" * 24, "c" * 24, "b" * 24)))

    def test_no_key_or_an_outage_marks_no_review(self):
        archive = [{"id": c * 24, "artist_name": c, "album": c, "published": f"2020-01-0{i + 1}"} for i, c in enumerate("abcdef")]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(archive))
            with mock.patch.object(briefs, "DATA", p), \
                    mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: "x " * 300 for i in ids}):
                with mock.patch.object(briefs.llm, "available", return_value=False), mock.patch.object(briefs.llm, "summarize") as s:
                    briefs.run()
                    s.assert_not_called()
                self.assertEqual(json.loads((p / "briefs.json").read_text()), {})
                with mock.patch.object(briefs.llm, "available", return_value=True), \
                        mock.patch.object(briefs.llm, "summarize", return_value=None) as s:
                    briefs.run()
                    self.assertEqual(s.call_count, briefs.GIVE_UP)
                self.assertEqual(json.loads((p / "briefs.json").read_text()), {})

    def test_failed_rewrites_stop_an_outage_too_and_keep_the_old_briefs(self):
        archive = [{"id": c * 24, "artist_name": c, "album": c, "published": f"2020-01-0{i + 1}"} for i, c in enumerate("abcdefg")]
        old = {c * 24: {"brief": "Старое.", "p": 2} for c in "abcdefg"}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(archive))
            (p / "briefs.json").write_text(json.dumps(old))
            with mock.patch.object(briefs, "DATA", p), mock.patch.dict(os.environ, {"BRIEFS_LANG": "both"}), \
                    mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: "x " * 300 for i in ids}), \
                    mock.patch.object(briefs.llm, "available", return_value=True), \
                    mock.patch.object(briefs.llm, "summarize", return_value=None) as s:
                briefs.run()
            self.assertEqual(s.call_count, briefs.GIVE_UP)  # not all 7: the balance ran out, say
            self.assertEqual(json.loads((p / "briefs.json").read_text()), old)

    def test_a_rewrite_that_keeps_failing_is_left_with_its_old_brief(self):
        archive = [{"id": c * 24, "artist_name": c, "album": c, "published": f"2020-01-0{i + 1}"} for i, c in enumerate("ab")]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(archive))
            (p / "briefs.json").write_text(json.dumps({"a" * 24: {"brief": "Старое.", "p": 2}}))
            for n in range(1, 3):
                with mock.patch.object(briefs, "DATA", p), mock.patch.dict(os.environ, {"BRIEFS_LANG": "both"}), \
                        mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: "x " * 300 for i in ids}), \
                        mock.patch.object(briefs.llm, "available", return_value=True), \
                        mock.patch.object(briefs.llm, "summarize", side_effect=lambda t, *a, **kw: None if t.startswith("a") else dict(ANSWER, model="m")):
                    briefs.run()
                out = json.loads((p / "briefs.json").read_text())
                self.assertEqual(out["a" * 24], {"brief": "Старое.", "p": 2, "rf": n, "rf_p": briefs.PROMPT_V})
            self.assertTrue(briefs.finished(out["a" * 24], "both"))  # FAIL_MAX runs: not paid for again
            with mock.patch.object(briefs, "PROMPT_V", briefs.PROMPT_V + 1):
                self.assertFalse(briefs.finished(out["a" * 24], "both"))  # a new prompt tries it again

    def test_a_run_stops_at_its_spending_cap(self):
        archive = [{"id": c * 24, "artist_name": c, "album": c, "published": f"2020-01-0{i + 1}"} for i, c in enumerate("abcd")]

        def paid(*a, **kw):
            llm.stats["rub"] += 0.6
            return dict(ANSWER, model="m")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(archive))
            with mock.patch.object(briefs, "DATA", p), mock.patch.dict(os.environ, {"BRIEFS_MAX_RUB": "1"}), \
                    mock.patch.dict(llm.stats, {"rub": 0.0, "timeouts": 0}), \
                    mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: "x " * 300 for i in ids}), \
                    mock.patch.object(briefs.llm, "available", return_value=True), \
                    mock.patch.object(briefs.llm, "summarize", side_effect=paid) as s:
                briefs.run()
            self.assertEqual(s.call_count, 2)  # 0.6, then 1.2 ≥ 1: no third
            self.assertEqual(len(json.loads((p / "briefs.json").read_text())), 2)

    def test_tnd_down_is_not_remembered(self):
        archive = [{"id": "a" * 24, "artist_name": "A", "album": "B", "published": "2020-01-01"}]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(archive))
            with mock.patch.object(briefs, "DATA", p), mock.patch.object(briefs.tnd, "fetch_texts", side_effect=OSError("down")):
                briefs.run()
            self.assertEqual(json.loads((p / "briefs.json").read_text()), {})


class English(unittest.TestCase):
    """BRIEFS_LANG=en: written in English, translated by Gemini in batches."""
    EN = {"brief": "Short, 7/10.", "about": "Longer.", "who": "", "moods": ["ночью"], "model": "g"}

    def archive(self, n):
        return [{"id": f"{i:024x}", "artist_name": f"A{i}", "album": f"B{i}", "published": f"2020-01-{i + 1:02d}", "score": 7}
                for i in range(n)]

    def fake_translate(self, items):
        return [{"brief": f"Ru {x['brief']}", "about": "Подробно.", "who": "", "tr": "gm"} for x in items]

    def run_briefs(self, p, summarize, translate, env=None):
        with mock.patch.object(briefs, "DATA", p), mock.patch.dict(os.environ, {"BRIEFS_LANG": "en", **(env or {})}), \
                mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: "x " * 300 for i in ids}), \
                mock.patch.object(briefs.llm, "available", return_value=True), \
                mock.patch.object(briefs.llm, "summarize", side_effect=summarize) as s, \
                mock.patch.object(briefs.gemini, "translate", side_effect=translate) as t:
            briefs.run()
        return s, t, json.loads((p / "briefs.json").read_text())

    def test_batches_of_ten_and_the_rest_at_the_end(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(self.archive(12)))
            s, t, out = self.run_briefs(p, lambda *a, **kw: dict(self.EN), self.fake_translate)
            self.assertEqual([len(c.args[0]) for c in t.call_args_list], [10, 2])
            self.assertEqual(s.call_args.kwargs, {"lang": "en", "verdict": briefs.verdict({"score": 7}), "tags": []})
            e = out[f"{0:024x}"]
            self.assertEqual(e, {"brief": "Ru Short, 7/10.", "about": "Подробно.", "tr": "gm", "m": "g", "moods": ["ночью"], "p": briefs.PROMPT_V,
                                 "en": {"brief": "Short, 7/10.", "about": "Longer."}})

    def test_failed_translation_waits_and_is_not_written_again(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(self.archive(3)))
            _, t, out = self.run_briefs(p, lambda *a, **kw: dict(self.EN), lambda items: None)
            self.assertEqual(t.call_count, 1)
            self.assertEqual(briefs.untranslated(out), [f"{i:024x}" for i in range(3)])
            s, t, out = self.run_briefs(p, lambda *a, **kw: dict(self.EN), self.fake_translate)
            s.assert_not_called()
            self.assertEqual(briefs.untranslated(out), [])
            self.assertEqual(out[f"{2:024x}"]["brief"], "Ru Short, 7/10.")

    def test_the_translation_budget_holds(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(self.archive(25)))
            _, t, out = self.run_briefs(p, lambda *a, **kw: dict(self.EN), self.fake_translate, {"BRIEFS_TRANSLATE_MAX": "2"})
            self.assertEqual(t.call_count, 2)
            self.assertEqual(len(briefs.untranslated(out)), 5)

    def test_old_russian_briefs_are_written_again_and_kept_if_that_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(self.archive(2)))
            old = {"brief": "Калька.", "m": "openai/gpt-oss-120b"}
            (p / "briefs.json").write_text(json.dumps({f"{0:024x}": old, f"{1:024x}": old}))
            answers = iter([None, dict(self.EN)])  # newest first: 1 fails, 0 gets a new one
            _, _, out = self.run_briefs(p, lambda *a, **kw: next(answers), lambda items: None)
            self.assertEqual(out[f"{1:024x}"], {**old, "rf": 1, "rf_p": briefs.PROMPT_V})  # kept; tried again in one more run only
            self.assertEqual(out[f"{0:024x}"]["brief"], "Калька.")  # on the site until the translation comes
            self.assertEqual(briefs.untranslated(out), [f"{0:024x}"])
            s, _, out = self.run_briefs(p, lambda *a, **kw: dict(self.EN), self.fake_translate)
            self.assertEqual(s.call_count, 1)  # only 1 written again; 0 just translated
            self.assertEqual(out[f"{0:024x}"]["brief"], "Ru Short, 7/10.")
            self.assertEqual(out[f"{0:024x}"]["about"], "Подробно.")

    def test_an_empty_translation_is_not_tried_forever(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(self.archive(1)))
            for _ in range(3):
                _, t, out = self.run_briefs(p, lambda *a, **kw: dict(self.EN), lambda items: [{"brief": "", "tr": "gm"} for _ in items])
            self.assertEqual(t.call_count, 0)
            self.assertEqual(out[f"{0:024x}"]["trf"], briefs.TR_FAIL_MAX)
            self.assertEqual(briefs.untranslated(out), [])

    def test_briefs_by_the_old_prompt_are_written_again(self):
        self.assertFalse(briefs.finished({"brief": "x", "en": {"brief": "y"}, "tr": "gm"}, "en"))
        self.assertTrue(briefs.finished({"brief": "x", "en": {"brief": "y"}, "tr": "gm", "p": briefs.PROMPT_V}, "en"))
        self.assertTrue(briefs.finished({"skip": "short"}, "en"))
        self.assertEqual(briefs.entry({"brief": "b"}, "en")["p"], briefs.PROMPT_V)

    def test_the_score_is_cut_from_the_text(self):
        d = gemini.drop_score
        self.assertEqual(d("Третий альбом Remi Wolf «Mud» уходит в чистый акустический поп, однако Фантано считает его безликим и ставит 4/10."),
                         "Третий альбом Remi Wolf «Mud» уходит в чистый акустический поп, однако Фантано считает его безликим.")
        self.assertEqual(d("Alabama Shakes возвращаются с третьим альбомом «I Must Be Dreaming», получая от Фантано оценку 6/10."),
                         "Alabama Shakes возвращаются с третьим альбомом «I Must Be Dreaming».")
        self.assertEqual(d("Пятый альбом Fontaines D.C. «Dopamine Chamber» расширяет звучание; Фантано оценивает его на 7/10."),
                         "Пятый альбом Fontaines D.C. «Dopamine Chamber» расширяет звучание.")
        self.assertEqual(d("Альбом Kid Rock «Halfway 2 Jesus» — кантри-рок, однако Фантано считает его NOT GOOD."),
                         "Альбом Kid Rock «Halfway 2 Jesus» — кантри-рок.")
        self.assertEqual(d("Ровно. В итоге Фантано оценивает пластинку на 6/10, называя ее неоднозначной."), "Ровно.")
        self.assertEqual(d("Quavo's album is a summer trap record that earns Fantano a 5/10."), "Quavo's album is a summer trap record.")
        self.assertEqual(d("Фантано оценивает пластинку на 5/10."), "Фантано оценивает пластинку на 5/10.")  # nothing else to keep
        self.assertEqual(d("Без оценки."), "Без оценки.")

    def test_verdict_never_invents_a_score(self):
        self.assertEqual(briefs.verdict({"score": 0}), "Fantano's score: 0/10. The card shows it above your text: never write it.")
        self.assertIn('"NOT GOOD"', briefs.verdict({"score": None, "not_good": True}))
        self.assertIn('"CLASSIC"', briefs.verdict({"classic": True}))
        self.assertEqual(briefs.verdict({}), "Fantano gave no score: don't write one.")
        self.assertIn("NOT GOOD", gemini.PROMPT_EN.format(moods="[]", title="t", text="x", verdict=briefs.verdict({"not_good": True})))


class Site(unittest.TestCase):
    A = {"id": "a" * 24, "url": "https://theneedledrop.com/x", "published": "2020-01-01", "artist_name": "Radiohead",
         "album": "Kid A", "score": 10}

    def test_archive_page_shows_the_long_brief_and_hides_the_quote(self):
        html = site.archive_page(self.A, [self.A], note={"blurb": "Fantano's line."},
                                 brief={"brief": "Коротко.", "about": "Длинно и подробно.", "who": "Группа из Оксфорда."})
        self.assertIn("<dt>Кто</dt><dd>Группа из Оксфорда.</dd><dt>Описание</dt><dd>Длинно и подробно.</dd>", html)
        self.assertNotIn("Fantano&#x27;s line", html)
        self.assertNotIn("Коротко.", html)

    def test_release_page_without_a_card_brief_takes_the_archive_one(self):
        r = dict(self.A, genres=[], ai={"brief": None, "who": "Своё."})
        html = site.release_page(r, brief={"brief": "Коротко.", "about": "Длинно.", "who": "Чужое."})
        self.assertIn("<dd>Длинно.</dd>", html)
        self.assertIn("Своё.", html)
        self.assertNotIn("Чужое.", html)



class CompareModels(unittest.TestCase):
    def test_two_done_reviews_each_other_model_one_translation(self):
        archive = [{"id": f"{i:024x}", "artist_name": f"A{i}", "album": f"B{i}", "published": f"2026-10-{10 + i}T00:00:00Z",
                    "score": 7} for i in range(4)]
        data = {a["id"]: {"brief": "Кратко.", "about": "Об альбоме.", "who": "Кто.", "tr": "gemini-3.5-flash"} for a in archive[:3]}
        asked = []

        def ask(provider, title, text, model=None, **kw):
            asked.append((title, model))
            return {"brief": f"{model} brief", "model": model}
        with mock.patch.object(briefs, "texts", side_effect=lambda items: ((a, "text " * 200) for a in items)), \
                mock.patch.object(briefs.llm, "ask", side_effect=ask), \
                mock.patch.object(briefs.gemini, "translate", side_effect=lambda xs: [{"brief": "RU " + x["brief"], "tr": "g"} for x in xs]) as tr, \
                mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}):
            rows = briefs.compare(archive, [], data)
        self.assertEqual([r["title"] for r in rows], ["A2 - B2", "A1 - B1"])  # newest that 120b wrote; A3 has none
        self.assertEqual(len(asked), 4)
        self.assertEqual(tr.call_count, 1)  # one Gemini request for all
        self.assertEqual(rows[0]["qwen/qwen3.8-27b"]["brief"], "RU qwen/qwen3.8-27b brief")
        self.assertEqual(rows[0][briefs.CURRENT]["brief"], "Кратко.")

    def test_selectel_models_write_russian_themselves_with_their_tokens(self):
        archive = [{"id": f"{i:024x}", "artist_name": f"A{i}", "album": f"B{i}", "published": f"2026-10-{10 + i}T00:00:00Z",
                    "score": 7} for i in range(2)]
        data = {a["id"]: {"brief": "Кратко.", "tr": "g"} for a in archive}
        asked = []

        def ask(provider, title, text, model=None, lang=None, verdict="", tags=(), short=False):
            asked.append((provider, model, lang, verdict))
            return {"brief": "Сразу по-русски.", "model": model, "usage": {"prompt_tokens": 9000, "completion_tokens": 700}}
        with mock.patch.object(briefs, "texts", side_effect=lambda items: ((a, "text " * 200) for a in items)), \
                mock.patch.object(briefs.llm, "ask", side_effect=ask), \
                mock.patch.object(briefs.gemini, "translate") as tr, \
                mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": "", "BRIEFS_COMPARE_MODELS": "selectel:deepseek/x"}):
            rows = briefs.compare(archive, [], data)
        tr.assert_not_called()  # no translation: the model wrote Russian
        self.assertEqual(asked[0][:3], ("selectel", "deepseek/x", "both"))
        self.assertIn("7/10", asked[0][3])  # the verdict goes to the Russian prompt too
        self.assertEqual({k: rows[0]["selectel:deepseek/x"][k] for k in ("brief", "in", "out")},
                         {"brief": "Сразу по-русски.", "in": 9000, "out": 700})


class Selectel(unittest.TestCase):
    def test_both_languages_never_fall_back_to_groq(self):
        llm._dead.clear()
        llm._spent.clear()
        with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "", "GROQ_API_KEY": "g", "MISTRAL_API_KEY": ""}), \
                mock.patch.object(llm.http, "get_json") as get:
            self.assertFalse(llm.available("both"))
            self.assertTrue(llm.available("en"))
            self.assertIsNone(llm.summarize("A - B", "text", lang="both", sleep=lambda s: None))
        get.assert_not_called()  # Groq's own Russian was rejected: no text rather than a worse one

    def test_both_languages_in_one_answer_need_no_translation(self):
        out = gemini.parse_answer(json.dumps(dict(ANSWER, en={"brief": "Dense and noisy. He gives it a 7/10.", "who": "Oxford band; fourth album.", "x": 1})))
        self.assertEqual(out["en"], {"brief": "Dense and noisy.", "who": "Oxford band; fourth album."})  # the score cut here too
        e = briefs.entry({**out, "model": "m1"}, "both")
        self.assertEqual((e["brief"], e["tr"], e["en"]["who"]), ("Коротко.", "m1", "Oxford band; fourth album."))
        self.assertTrue(briefs.finished(e, "both"))
        self.assertEqual(briefs.untranslated({"k": e}), [])  # its own translation: Gemini is not asked
        with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "k"}), mock.patch.object(llm.http, "get_json", return_value=chat(ANSWER)) as get:
            llm.ask("selectel", "A - B", "text", model="m1", lang="both", sleep=lambda s: None)
        self.assertIn('"en": объект', get.call_args.kwargs["json_body"]["messages"][0]["content"])


    def test_skipped_until_a_model_is_set_then_asked_in_russian_with_low_reasoning(self):
        llm._dead.clear()
        llm._spent.clear()
        with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "k", "GROQ_API_KEY": "", "MISTRAL_API_KEY": ""}), \
                mock.patch.object(llm.http, "get_json") as get:
            self.assertFalse(llm.available())  # a key without a model: not used
            self.assertIsNone(llm.ask("selectel", "A - B", "text"))
            get.assert_not_called()
            get.return_value = {"choices": [{"message": {"content": "```json\n" + json.dumps(ANSWER, ensure_ascii=False) + "\n```"}}],
                                "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
            out = llm.ask("selectel", "A - B", "text", model="m1", sleep=lambda s: None, verdict="Fantano's score: 7/10.")
        body = get.call_args.kwargs["json_body"]
        self.assertEqual((body["model"], body["reasoning"]), ("m1", {"effort": "low"}))
        self.assertIn("на русском", body["messages"][0]["content"])
        self.assertNotIn('"en": объект', body["messages"][0]["content"])  # English only when asked for both
        self.assertIn("7/10", body["messages"][0]["content"])
        self.assertEqual((out["brief"], out["usage"]["completion_tokens"]), ("Коротко.", 3))  # a fenced answer is read too

    def test_a_gone_or_unpaid_model_stops_the_provider_without_picking_another(self):
        for status, body in ((404, '{"error": "model not found"}'), (402, '{"error": "insufficient balance"}')):
            llm._dead.clear()
            with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "k"}), \
                    mock.patch.object(llm.http, "get_json", side_effect=llm.http.HttpError(status, body, "u")) as get, \
                    mock.patch.object(llm, "pick_model") as pick:
                self.assertIsNone(llm.ask("selectel", "A - B", "text", model="m1", lang="both", sleep=lambda s: None))
            pick.assert_not_called()  # a model from the catalogue could cost anything
            self.assertEqual(get.call_count, 1)
            self.assertIn("selectel", llm._dead)
        llm._dead.clear()

    def test_charges_and_timeouts_are_counted(self):
        answer = dict(chat(ANSWER), usage={"cost": 0.25})
        with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "k"}), mock.patch.dict(llm.stats, {"rub": 0.0, "timeouts": 0}):
            with mock.patch.object(llm.http, "get_json", return_value=answer):
                llm.ask("selectel", "A - B", "text", model="m1", lang="both", sleep=lambda s: None)
            with mock.patch.object(llm.http, "get_json", return_value={"usage": {"cost": 0.5}, "choices": []}):
                llm.ask("selectel", "A - B", "text", model="m1", lang="both", sleep=lambda s: None)  # unreadable, still paid
            with mock.patch.object(llm.http, "get_json", side_effect=llm.http.HttpError(0, "timed out", "u")):
                llm.ask("selectel", "A - B", "text", model="m1", lang="both", sleep=lambda s: None)
            self.assertEqual((llm.stats["rub"], llm.stats["timeouts"]), (0.75, 1))

    def test_an_answer_without_its_cost_is_warned_about_once(self):
        with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "k"}), mock.patch.dict(llm.stats, {"rub": 0.0, "no_cost": False}), \
                mock.patch.object(llm.http, "get_json", return_value=chat(ANSWER)), mock.patch("builtins.print") as p:
            for _ in range(2):
                llm.ask("selectel", "A - B", "text", model="m1", lang="both", sleep=lambda s: None)
        self.assertEqual(sum("no usage.cost" in str(c) for c in p.call_args_list), 1)

    def test_the_sites_tags_go_into_the_russian_prompt(self):
        self.assertEqual(briefs.tags({"genres": ["Country", " rap rock ", "", None]}), ["Country", "rap rock"])
        self.assertEqual(briefs.tags({}), [])
        with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "k"}), mock.patch.object(llm.http, "get_json", return_value=chat(ANSWER)) as get:
            llm.ask("selectel", "A - B", "text", model="m1", lang="both", sleep=lambda s: None, tags=["Country", "rap rock"])
            self.assertIn("Теги: Country, rap rock.\nТекст обзора:", get.call_args.kwargs["json_body"]["messages"][0]["content"])
            llm.ask("selectel", "A - B", "text", model="m1", lang="both", sleep=lambda s: None)
            self.assertNotIn("Теги:", get.call_args.kwargs["json_body"]["messages"][0]["content"])


class Short(unittest.TestCase):
    """Reviews that are only a video: Fantano's own short lines told in Russian and English (2026-11-04)."""

    def test_his_lines_once_each(self):
        self.assertEqual(briefs.short_lines("A dark record.", {"blurb": "A dark record. Great drums."}), "A dark record. Great drums.")
        self.assertEqual(briefs.short_lines("Line under the video.", {"blurb": "Blurb."}), "Line under the video.\nBlurb.")
        self.assertEqual(briefs.short_lines("", None), "")

    def test_a_short_review_is_told_from_his_lines_and_an_empty_one_is_left(self):
        archive = [{"id": c * 24, "artist_name": c, "album": c, "published": f"2015-01-0{i + 1}", "genres": ["noise rock"]}
                   for i, c in enumerate("abc")]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(archive))
            (p / "briefs.json").write_text(json.dumps({c * 24: {"skip": "short"} for c in "abc"}))
            (p / "notes.json").write_text(json.dumps({"c" * 24: {"blurb": "Noisy, abrasive and almost gothic. The hooks are weak."}}))
            texts = {"c" * 24: "On their debut, a dark and abrasive take on noise rock.", "b" * 24: "WATCH", "a" * 24: "y " * 300}
            asked = []

            def summarize(title, text, **kw):
                asked.append((title, text, kw.get("short")))
                return dict(ANSWER, model="m", en={"brief": "Dark.", "who": "Band."})
            with mock.patch.object(briefs, "DATA", p), mock.patch.dict(os.environ, {"BRIEFS_LANG": "both"}), \
                    mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: texts[i] for i in ids}), \
                    mock.patch.object(briefs.llm, "available", return_value=True), \
                    mock.patch.object(briefs.llm, "summarize", side_effect=summarize):
                briefs.run()
            out = json.loads((p / "briefs.json").read_text())
        self.assertEqual(asked[0], ("c - c", texts["c" * 24] + "\nNoisy, abrasive and almost gothic. The hooks are weak.", True))
        self.assertEqual(asked[1][2], None)  # a whole review text: the usual prompt
        self.assertEqual((out["c" * 24]["src"], out["c" * 24]["brief"], out["c" * 24]["en"]["who"]), ("short", "Коротко.", "Band."))
        self.assertEqual(out["b" * 24], {"skip": "short", "short": "none"})  # nothing to tell: not asked, not fetched again
        self.assertTrue(all(briefs.finished(out[k], "both") for k in out))
        self.assertFalse(briefs.finished({"skip": "short"}, "both"))
        self.assertTrue(briefs.finished({"skip": "short"}, "ru"))

    def test_lines_with_nothing_on_the_music_are_an_answer_not_a_failure(self):
        archive = [{"id": c * 24, "artist_name": c, "album": c, "published": f"2015-01-0{i + 1}"} for i, c in enumerate("abcdefg")]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps(archive))
            (p / "briefs.json").write_text(json.dumps({c * 24: {"skip": "short"} for c in "abcdefg"}))
            answer = dict(ANSWER, brief="", about="", who="Рэпер из Атланты.", en={"who": "Atlanta rapper."})
            with mock.patch.object(briefs, "DATA", p), mock.patch.dict(os.environ, {"BRIEFS_LANG": "both"}), \
                    mock.patch.object(briefs.tnd, "fetch_texts", side_effect=lambda ids: {i: "Odd Future's rapper returns with his long-awaited major label debut." for i in ids}), \
                    mock.patch.object(briefs.llm, "available", return_value=True), \
                    mock.patch.object(briefs.llm, "summarize", return_value=dict(gemini.parse_answer(json.dumps(answer)), model="m")) as s:
                briefs.run()
            out = json.loads((p / "briefs.json").read_text())
        self.assertEqual(s.call_count, 7)  # all of them: not an outage after 5
        self.assertEqual(out["a" * 24], {"skip": "short", "short": "none", "who": "Рэпер из Атланты.", "en": {"who": "Atlanta rapper."}, "m": "m", "p": briefs.PROMPT_V})
        self.assertTrue(all(briefs.finished(v, "both") for v in out.values()))

    def test_summarize_takes_an_empty_brief_only_from_short_lines(self):
        llm._dead.clear()
        llm._spent.clear()
        empty = chat(dict(ANSWER, brief=""))
        with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "k", "SELECTEL_MODEL": "m1", "MISTRAL_API_KEY": "", "GROQ_API_KEY": ""}), \
                mock.patch.object(llm, "PROVIDERS", [("selectel", "u", "SELECTEL_API_KEY", "m1", 0, 30000)]), \
                mock.patch.object(llm.http, "get_json", return_value=empty):
            self.assertIsNone(llm.summarize("A - B", "text", lang="both", sleep=lambda s: None))
            self.assertIsNotNone(llm.summarize("A - B", "text", lang="both", short=True, sleep=lambda s: None))

    def test_the_short_prompt_has_only_his_lines_and_no_about(self):
        with mock.patch.dict(os.environ, {"SELECTEL_API_KEY": "k"}), mock.patch.object(llm.http, "get_json", return_value=chat(ANSWER)) as get:
            llm.ask("selectel", "A - B", "His line.", model="m1", lang="both", sleep=lambda s: None, tags=["noise rock"], short=True)
        prompt = get.call_args.kwargs["json_body"]["messages"][0]["content"]
        self.assertIn("Фразы Фантано:\nHis line.", prompt)
        self.assertIn("Теги: noise rock.", prompt)
        self.assertIn('"en": объект с полями "brief" и "who"', prompt)
        self.assertNotIn('"about"', prompt)


if __name__ == "__main__":
    unittest.main()
