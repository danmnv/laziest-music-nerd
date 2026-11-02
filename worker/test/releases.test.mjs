import { test } from "node:test";
import assert from "node:assert/strict";
import { sortOut, quietHour, ruDate } from "../src/releases.mjs";

const today = new Date("2026-11-06T12:00:00Z");
const a = (id, title, release_date, record_type = "album") => ({ id, title, release_date, record_type });

test("the first check only remembers what is out, not what is announced", () => {
  const r = sortOut([a(1, "Old", "2020-01-01"), a(2, "Soon", "2026-12-01"), a(3, "Today", "2026-11-06")], null, today);
  assert.deepEqual(r, { fresh: [], seen: [1, 3] });
});

test("albums and EPs out in the last two weeks are new; singles, late catalogue, re-releases aren't", () => {
  const r = sortOut([
    a(10, "New LP", "2026-11-06"), a(11, "New EP", "2026-11-01", "ep"), a(12, "Single", "2026-11-06", "single"),
    a(13, "Found late", "2026-09-01"), a(14, "Old (Remastered)", "2026-11-06"), a(15, "Old LP (Deluxe)", "2026-11-06"),
    a(16, "Old LP", "2026-11-06"), a(1, "Old LP", "2019-05-05"), a(17, "Soon", "2026-11-07")], [1], today);
  assert.deepEqual(r.fresh.map((x) => x.id), [10, 11]);
  assert.deepEqual(r.seen, [1, 10, 11, 12, 13, 14, 15, 16]); // "Soon" waits for its day
});

test("quiet hours are 01–09 in Moscow", () => {
  assert.equal(quietHour(new Date("2026-11-06T22:00:00Z")), true);
  assert.equal(quietHour(new Date("2026-11-06T05:59:00Z")), true);
  assert.equal(quietHour(new Date("2026-11-06T06:00:00Z")), false);
  assert.equal(ruDate("2026-10-31"), "31 октября");
});

import { isGenre, genresOf } from "../src/genres.mjs";
test("genres: TND's site words, labels and places don't count; the stored tags stay", () => {
  assert.deepEqual(["shoegaze", "vlog", "music", "atlantic", "sub pop", "deconstructed club", "uk", "neofolk"].filter(isGenre),
    ["shoegaze", "deconstructed club", "neofolk"]);
  const a = { genres: ["music", "art rock"] };
  assert.deepEqual(genresOf(a), ["art rock"]);
  assert.deepEqual(a.genres, ["music", "art rock"]);
});
