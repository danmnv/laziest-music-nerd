import { test } from "node:test";
import assert from "node:assert/strict";
import { searchArchive, badge } from "../src/search.mjs";

const A = [
  { id: "1", artist_name: "Radiohead", album: "Kid A", published: "2020-01-01", score: 10 },
  { id: "2", artist_name: "Radiohead", album: "A Moon Shaped Pool", published: "2016-05-10", score: 8 },
  { id: "3", artist_name: "Thom Yorke", album: "Anima", published: "2019-07-01", score: 7 },
  { id: "4", artist_name: "Radiohead Tribute Band", album: "Covers", published: "2024-01-01", score: 2 },
  { id: "5", artist_name: "Beyoncé", album: "Renaissance", published: "2022-08-01", score: 7 },
  { id: "6", artist_name: "Кино", album: "Группа крови", published: "2011-01-01", score: null },
];

test("every word must match the artist or the album, in any order", () => {
  assert.deepEqual(searchArchive(A, "kid a radiohead").items.map((a) => a.id), ["1"]);
  assert.deepEqual(searchArchive(A, "anima").items.map((a) => a.id), ["3"]);
  assert.equal(searchArchive(A, "nothing like this").total, 0);
  assert.equal(searchArchive(A, "   ").total, 0);
});

test("the artist named exactly comes first, newest first", () => {
  assert.deepEqual(searchArchive(A, "radiohead").items.map((a) => a.id), ["1", "2", "4"]);
});

test("accents, case and Cyrillic", () => {
  assert.deepEqual(searchArchive(A, "beyonce").items.map((a) => a.id), ["5"]);
  assert.deepEqual(searchArchive(A, "КИНО").items.map((a) => a.id), ["6"]);
});

test("limit keeps the total", () => {
  const r = searchArchive(A, "a", 2);
  assert.equal(r.items.length, 2);
  assert.ok(r.total > 2);
});

test("badges", () => {
  assert.equal(badge({ score: 8 }), "🟢 8/10");
  assert.equal(badge({ score: 5 }), "🟡 5/10");
  assert.equal(badge({ score: 3 }), "🔴 3/10");
  assert.equal(badge({ not_good: true, score: null }), "🔴 NOT GOOD");
  assert.equal(badge({ classic: true }), "🟢 CLASSIC");
  assert.equal(badge({ score: null }), "⚪ без оценки");
});

import { answerSearch, artistReviews } from "../src/search.mjs";

test("an artist named exactly: all their reviews, other artists counted", () => {
  const r = answerSearch(A, "radiohead");
  assert.equal(r.kind, "albums");
  assert.equal(r.artist, "Radiohead");
  assert.deepEqual(r.items.map((a) => a.id), ["1", "2"]);
  assert.equal(r.others, 1); // the tribute band
});

test("one hit is a card; nothing is none", () => {
  assert.equal(answerSearch(A, "anima").kind, "card");
  assert.equal(answerSearch(A, "zzz").kind, "none");
});

test("many hits across artists: pick the artist first, the most reviewed first", () => {
  const many = [];
  for (let i = 0; i < 6; i++) many.push({ id: `b${i}`, artist_name: "Big Band", album: `Love ${i}`, published: `2020-0${i + 1}-01` });
  for (let i = 0; i < 4; i++) many.push({ id: `s${i}`, artist_name: "Small Band", album: `Love ${i}`, published: `2021-0${i + 1}-01` });
  const r = answerSearch(many, "love");
  assert.equal(r.kind, "artists");
  assert.deepEqual(r.artists.map((x) => [x.name, x.count]), [["Big Band", 6], ["Small Band", 4]]);
  const few = answerSearch(many.slice(3, 9), "love"); // 6 hits: shown as albums directly
  assert.equal(few.kind, "albums");
  assert.equal(few.artist, null);
});

test("an artist's reviews from any one of them", () => {
  const r = artistReviews(A, "2");
  assert.equal(r.artist, "Radiohead");
  assert.deepEqual(r.items.map((a) => a.id), ["1", "2"]);
  assert.equal(artistReviews(A, "nope").total, 0);
});
