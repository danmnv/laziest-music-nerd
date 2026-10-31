"""Limits and failures: Telegram length rules, Gemini model fallback, one broken source."""
import json
import re
import unittest
from unittest import mock

from lmn import card, enrich as enrich_mod, gemini, http, tnd


def post(title, tags):
    return {"id": "6ae16e7060a520b7b082e3e1", "title": title, "slug": "x", "url": "https://theneedledrop.com/album-reviews/x/",
            "published_at": "2026-10-22T07:22:16.000-04:00", "canonical_url": "", "tags": [{"name": t} for t in tags], "plaintext": ""}


def balanced(text):
    for tag in ("b", "blockquote", "a"):
        if len(re.findall(f"<{tag}[ >]", text)) != text.count(f"</{tag}>"):
            return False
    return True


class TelegramLengthTest(unittest.TestCase):
    def test_tg_len_counts_visible_text_in_utf16(self):
        self.assertEqual(card.tg_len('<a href="https://example.com/very/long/url">AB</a> &amp; 🟢'), 7)

    def test_escaped_chars_dont_shrink_the_tracklist(self):
        r = tnd.parse_post(post("A - B", ["Album Reviews", "7/10"]))
        r.update(previous=[], previous_unsure=0, artist={}, links={},
                 tracks=[{"title": f"Rock & Roll & Blues & Jazz & Soul {i}", "sec": 200} for i in range(18)])
        c = card.caption(r)
        self.assertGreater(len(c), card.CAPTION_LIMIT)  # raw HTML is longer than 1024 because of &amp;
        self.assertLessEqual(card.tg_len(c), card.CAPTION_LIMIT)
        self.assertIn("18. Rock &amp; Roll", c)  # but Telegram counts the visible text, so every track still fits

    def test_huge_fields_never_cut_html(self):
        r = tnd.parse_post(post("A - B", ["Album Reviews", "7/10"]))
        r.update(previous=[{"album": "X" * 300, "score": 5}] * 4, previous_unsure=0, artist={}, links={},
                 tracks=[{"title": "T" * 80, "sec": 200}] * 30,
                 ai={"brief": "Б" * 900, "who": "W" * 900, "moods": ["для тусовки"]})
        c = card.caption(r)
        self.assertLessEqual(card.tg_len(c), card.CAPTION_LIMIT)
        self.assertTrue(balanced(c), c)
        r.update(artist_name="N" * 3000)
        c = card.caption(r)
        self.assertLessEqual(card.tg_len(c), card.CAPTION_LIMIT)
        self.assertTrue(balanced(c), c)

    def test_list_counts_visible_text_not_link_urls(self):
        url = "https://danmnv.github.io/laziest-music-nerd/r/" + "x" * 150 + ".html"
        items = [{"id": str(i), "line": f'🟡 7 · <a href="{url}">Artist {i} — Album {i}</a> · art pop · 40 мин'} for i in range(60)]
        text = card.render_list(items)
        self.assertIn("Album 59", text)  # 60 lines of ~50 visible chars fit, though the raw HTML is ~13k chars
        self.assertLessEqual(card.tg_len(text), card.MESSAGE_LIMIT)
        items = [{"id": str(i), "line": f'🟡 7 · <a href="{url}">{"Long title " * 10}{i}</a>'} for i in range(60)]
        text = card.render_list(items)
        self.assertLessEqual(card.tg_len(text), card.MESSAGE_LIMIT)
        self.assertNotIn(f'{"Long title " * 10}59', text)  # ~110 visible chars x 60 lines don't fit: the oldest go


def quota_error(per="PerDay"):
    body = json.dumps({"error": {"message": "You exceeded your current quota", "details": [
        {"violations": [{"quotaId": f"GenerateRequests{per}PerProjectPerModel-FreeTier", "quotaValue": "20"}]}]}})
    return http.HttpError(429, body, "url")


class GeminiFallbackTest(unittest.TestCase):
    def setUp(self):
        gemini._unavailable.clear()
        self.addCleanup(gemini._unavailable.clear)
        self.calls, self.sleeps = [], []

    def fake_get(self, answers):
        def get_json(url, **kw):
            model = url.split("/models/")[1].split(":")[0]
            self.calls.append(model)
            a = answers(model)
            if isinstance(a, Exception):
                raise a
            return a
        return get_json

    def test_daily_limit_moves_to_next_model_at_once_and_remembers(self):
        ok = {"candidates": [{"content": {"parts": [{"text": json.dumps({"brief": "Бриф", "moods": ["для тусовки", "x"]})}]}}]}
        answers = lambda m: quota_error() if m == gemini.MODELS[0] else ok
        with mock.patch.object(http, "get_json", self.fake_get(answers)):
            out = gemini.summarize("t", "text", api_key="k")
            self.assertEqual(out["moods"], ["для тусовки"])
            self.assertEqual(self.calls, gemini.MODELS[:2])
            gemini.summarize("t", "text", api_key="k")
        self.assertEqual(self.calls, gemini.MODELS[:2] + [gemini.MODELS[1]])  # the used-up model is skipped next time

    def test_overload_retries_once_per_model_and_never_sleeps_after_the_last_try(self):
        with mock.patch.object(http, "get_json", self.fake_get(lambda m: http.HttpError(503, "{}", "url"))):
            model, out = gemini.generate({}, "k", sleep=self.sleeps.append)
        self.assertIsNone(out)
        self.assertEqual(len(self.calls), 2 * len(gemini.MODELS))
        self.assertEqual(len(self.sleeps), len(gemini.MODELS))

    def test_time_budget_stops_the_review(self):
        now = [0.0]

        def slow(url, **kw):
            self.calls.append(kw["timeout"])
            now[0] += kw["timeout"]  # every call hangs until its timeout
            raise http.HttpError(0, "timeout", url)
        with mock.patch.object(http, "get_json", slow):
            gemini.generate({}, "k", budget=240, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
        self.assertLessEqual(now[0], 240)
        self.assertTrue(all(t <= gemini.CALL_TIMEOUT for t in self.calls))

    def test_bad_key_stops_at_once(self):
        with mock.patch.object(http, "get_json", self.fake_get(lambda m: http.HttpError(400, '{"error":{"message":"API key not valid"}}', "u"))):
            self.assertEqual(gemini.generate({}, "k", sleep=self.sleeps.append), (None, None))
        self.assertEqual(len(self.calls), 1)

    def test_quota_reason_names_the_limit(self):
        self.assertIn("GenerateRequestsPerDayPerProjectPerModel-FreeTier=20", gemini._reason(quota_error().body))


class EnrichSourceFailureTest(unittest.TestCase):
    def test_broken_musicbrainz_keeps_deezer_fields(self):
        rev = tnd.parse_post(post("Fontaines D.C. - Dopamine Chamber", ["Album Reviews", "7/10"]))
        dz = {"id": 1, "url": "https://www.deezer.com/album/1", "cover": "https://c/x.jpg", "duration_min": 44,
              "tracks": [{"title": "Big Fire", "sec": 201}]}
        with mock.patch.object(enrich_mod.mb, "find_release_group", side_effect=ValueError("bad JSON")), \
                mock.patch.object(enrich_mod.links, "deezer_album", return_value=dz), \
                mock.patch.object(enrich_mod.gemini, "summarize", side_effect=AssertionError("no AI when seeding")):
            r = enrich_mod.enrich(rev, "text", [], use_ai=False)
        self.assertEqual((r["duration_min"], r["tracks"][0]["title"]), (44, "Big Fire"))
        self.assertEqual(r["links"]["songlink"], "https://album.link/https://www.deezer.com/album/1")
        self.assertEqual(r["covers"][0], "https://c/x.jpg")
        self.assertEqual(r["ai"], {})


if __name__ == "__main__":
    unittest.main()
