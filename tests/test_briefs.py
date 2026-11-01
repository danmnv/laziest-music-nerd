import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lmn import briefs, deepl, gemini, http, llm, site

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

    def test_a_long_card_brief_keeps_whole_sentences_only_if_fantanos_view_stays(self):
        long_ = dict(ANSWER, brief="Новый альбом группы, где она пробует синт-фанк и поп. Фантано считает запись интересной. " + "Ещё слова. " * 20)
        out = gemini.parse_answer(json.dumps(long_))["brief"]
        self.assertLessEqual(len(out), gemini.BRIEF_MAX)
        self.assertTrue(out.startswith("Новый альбом группы, где она пробует синт-фанк и поп. Фантано считает запись интересной."))
        self.assertTrue(out.endswith("."))
        one = dict(ANSWER, brief="Новый альбом " + "очень " * 40 + "длинный; Фантано доволен.")
        self.assertEqual(gemini.parse_answer(json.dumps(one))["brief"], one["brief"])  # cutting would lose his view

    def test_moods_are_the_same_list_as_the_bots(self):
        import re
        js = (Path(__file__).parent.parent / "worker/src/index.js").read_text()
        block = re.search(r"const MOODS = \[(.*?)\];", js, re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', block), gemini.MOODS)


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


class DeepL(unittest.TestCase):
    def test_one_request_free_host_and_empty_fields_stay_empty(self):
        en = [{"brief": "Good.", "about": "Long.", "who": ""}]
        with mock.patch.object(http, "get_json", return_value={"translations": [{"text": "Хорошо."}, {"text": "Длинно."}, {"text": ""}]}) as g:
            out = deepl.translate(en, api_key="abc:fx")
        self.assertTrue(g.call_args.args[0].startswith("https://api-free.deepl.com/"))
        self.assertEqual(g.call_args.kwargs["json_body"]["text"], ["Good.", "Long.", ""])
        self.assertEqual(out, [{"brief": "Хорошо.", "about": "Длинно.", "who": "", "tr": "deepl"}])
        with mock.patch.object(http, "get_json", side_effect=http.HttpError(456, "Quota exceeded", "u")):
            self.assertIsNone(deepl.translate(en, api_key="abc:fx"))
        self.assertIsNone(deepl.translate(en, api_key=""))


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

    def test_a_provider_still_limited_after_retries_is_left_for_the_run(self):
        calls = []

        def fake(url, **kw):
            calls.append(url.split("/")[2])
            if "mistral" in url:
                raise http.HttpError(429, '{"message":"Requests rate limit exceeded"}', url)
            return chat(ANSWER)

        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "m", "GROQ_API_KEY": "g", "CEREBRAS_API_KEY": ""}), \
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

        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "", "GROQ_API_KEY": "g", "CEREBRAS_API_KEY": ""}), \
                mock.patch.object(http, "get_json", side_effect=fake):
            out = llm.summarize("A - B", "text", sleep=lambda s: None)
            self.assertEqual(out["model"], "qwen/qwen3-32b")
            llm.summarize("A - C", "text", sleep=lambda s: None)
        self.assertEqual(calls, [("completions", "llama-3.3-70b-versatile"), ("models", None), ("completions", "qwen/qwen3-32b"),
                                 ("completions", "qwen/qwen3-32b")])
        llm._picked.clear()

    def test_no_keys_no_calls(self):
        with mock.patch.dict(os.environ, {"MISTRAL_API_KEY": "", "GROQ_API_KEY": "", "CEREBRAS_API_KEY": ""}), \
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
            self.assertEqual(s.call_args.kwargs, {"lang": "en", "verdict": briefs.verdict({"score": 7})})
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
            self.assertEqual(out[f"{1:024x}"], old)
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


if __name__ == "__main__":
    unittest.main()
