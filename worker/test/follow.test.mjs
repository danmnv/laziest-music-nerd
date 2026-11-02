import { test } from "node:test";
import assert from "node:assert/strict";
import { nameKey, followMatches } from "../src/follow.mjs";

test("names are compared without case, accents, spaces and punctuation; non-Latin names survive", () => {
  assert.equal(nameKey("Fontaines D.C."), nameKey("fontaines dc"));
  assert.equal(nameKey("Beyoncé"), "beyonce");
  assert.equal(nameKey("Simon & Garfunkel"), "simonandgarfunkel");
  assert.equal(nameKey("Кино"), "кино");
  assert.equal(nameKey("坂本龍一"), "坂本龍一");
  assert.equal(nameKey(""), "");
});

test("MusicBrainz ID decides when both sides have one", () => {
  const follow = { name_key: "low", mbid: "A" };
  assert.equal(followMatches(follow, { artist_name: "Low", mbid: "A" }), true);
  assert.equal(followMatches(follow, { artist_name: "Low", mbid: "B" }), false); // another band called Low
});

test("otherwise the name decides", () => {
  assert.equal(followMatches({ name_key: "hmltd", mbid: null }, { artist_name: "HMLTD", mbid: "X" }), true);
  assert.equal(followMatches({ name_key: "hmltd", mbid: "X" }, { artist_name: "HMLTD", mbid: null }), true);
  assert.equal(followMatches({ name_key: "hmltd", mbid: null }, { artist_name: "Shame", mbid: null }), false);
  assert.equal(followMatches({ name_key: "", mbid: null }, { artist_name: "", mbid: null }), false);
});
