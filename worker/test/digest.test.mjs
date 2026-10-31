import { test } from "node:test";
import assert from "node:assert/strict";
import { isDigestSunday } from "../src/digest.mjs";

const at7utc = (y, m, d) => new Date(Date.UTC(y, m - 1, d, 7)); // the cron fires Sundays 07:00 UTC = 10:00 MSK

function sundays(from, count) {
  const out = [];
  for (let i = 0; i < count; i++) out.push(new Date(from.getTime() + i * 7 * 864e5));
  return out;
}

test("first digest is on Sunday 1 Nov 2026, the next one two weeks later", () => {
  assert.equal(isDigestSunday(at7utc(2026, 11, 1)), true);
  assert.equal(isDigestSunday(at7utc(2026, 11, 8)), false);
  assert.equal(isDigestSunday(at7utc(2026, 11, 15)), true);
});

test("exactly every other Sunday across the 53-week year 2026 -> 2027 and over several years", () => {
  const all = sundays(at7utc(2026, 11, 1), 300);
  const sent = all.filter(isDigestSunday);
  for (let i = 1; i < sent.length; i++) assert.equal((sent[i] - sent[i - 1]) / 864e5, 14, sent[i].toISOString());
  assert.equal(sent.length, 150);
});

test("works for dates before the anchor too", () => {
  assert.equal(isDigestSunday(at7utc(2026, 10, 18)), true);
  assert.equal(isDigestSunday(at7utc(2026, 10, 25)), false);
});
