// The Worker's compact copy of the archive (archive.mjs): it must read back as archive.json does, and the bot must
// answer the same from either.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pack, unpack, plain, sharedTags, order, artistKey, albumKey, FORMAT } from "../src/archive.mjs";
import { searchArchive, artistReviews } from "../src/search.mjs";
import { nameKey } from "../src/follow.mjs";

const TND = "https://theneedledrop.com/album-reviews/";
const RAW = [
  { id: "a1", url: TND + "kid-a/", published: "2020-01-01T10:00:00Z", tnd_published: "2020-01-02", artist_name: "Radiohead", album: "Kid A", score: 10,
    classic: true, genres: ["Art Rock", "electronic"], video_id: "kidavideo01", artist_mbid: "R", score_source: "tnd" },
  { id: "a2", url: TND + "kid-a-again/", published: "2020-01-03T10:00:00Z", artist_name: "Radiohead", album: "Kid A", score: 10, dup_of: "a1", genres: ["art rock"] },
  { id: "a3", url: TND + "renaissance/", published: "2022-08-01T10:00:00Z", artist_name: "Beyoncé", album: "Renaissance", score: 7, genres: ["dance-pop", "house"] },
  { id: "a4", url: "https://www.youtube.com/watch?v=abc", published: "2011-01-01T10:00:00Z", artist_name: "Кино", album: "Группа крови", score: null, not_good: true, genres: [] },
  { id: "a5", url: TND + "guest/", published: "2019-07-01T10:00:00Z", artist_name: "Thom Yorke", album: "Anima", score: 7, guest: true, track: true },
  { id: "a6", url: TND + "pablo-redux/", published: "2018-02-01T10:00:00Z", artist_name: "Kanye West", album: "The Life of Pablo", score: 8,
    first: { y: 2016, score: 6 }, genres: ["hip hop", "odd|tag", "Electronic"], later_field: { any: ["thing"] } },
  { id: "a7", url: TND + "pablo/", published: "2016-02-20T10:00:00Z", artist_name: "Kanye West", album: "The Life of Pablo", score: 6, redo: { y: 2018, score: 8 }, genres: ["hip hop"] },
  { id: "a8", url: TND, published: "2015-01-01T10:00:00Z", artist_name: "Sufjan Stevens", album: "Carrie & Lowell", score: 9, genres: ["folk"] },
];
const FIELDS = ["id", "artist_name", "album", "published", "url", "score", "video_id", "first", "redo", "later_field"];
const FLAGS = ["classic", "not_good", "guest", "track"];
const through = (raw) => unpack(JSON.parse(JSON.stringify(pack(raw)))); // as the Worker gets it: through a file

test("the packed copy reads back as archive.json, field by field", () => {
  const got = through(RAW), want = plain(RAW);
  assert.equal(got.data.length, 7);
  assert.deepEqual(got.alias, { a2: "a1" });
  assert.deepEqual(got.alias, want.alias);
  got.data.forEach((a, i) => {
    const b = want.data[i];
    for (const f of FIELDS) assert.deepEqual(a[f] ?? null, b[f] ?? null, `${b.id} ${f}`);
    for (const f of FLAGS) assert.equal(!!a[f], !!b[f], `${b.id} ${f}`);
    assert.deepEqual(a.genres, b.genres || [], `${b.id} genres`);
    assert.equal(artistKey(a), nameKey(b.artist_name));
    assert.equal(albumKey(a), nameKey(b.album));
  });
});

test("what the copy saves on: the addresses' common start is kept once, the double post is left out", () => {
  const d = pack(RAW);
  assert.equal(d.v, FORMAT);
  assert.equal(d.u, TND);
  assert.equal(d.c.url[0], "kid-a/");
  assert.equal(d.c.url[2], "https://www.youtube.com/watch?v=abc"); // another site's address stays whole
  assert.equal(d.c.url.at(-1), TND); // nothing after the common start: kept whole
  assert.ok(!d.c.id.includes("a2"));
  assert.ok(!JSON.stringify(d).includes("artist_mbid") && !JSON.stringify(d).includes("tnd_published"));
});

test("genres can be set on a review read from the copy", () => {
  const a = through(RAW).data[0];
  a.genres = ["x"];
  assert.deepEqual(a.genres, ["x"]);
});

test("search and an artist's reviews answer the same from the copy", () => {
  const got = through(RAW).data, want = plain(RAW).data;
  for (const q of ["radiohead", "beyonce", "КИНО", "pablo kanye", "kid a", "carrie lowell", "nothing like this"]) {
    assert.deepEqual(searchArchive(got, q).items.map((a) => a.id), searchArchive(want, q).items.map((a) => a.id), q);
  }
  assert.deepEqual(artistReviews(got, "a6").items.map((a) => a.id), artistReviews(want, "a6").items.map((a) => a.id));
});

test("«похожие»: the same reviews and counts by tag from the copy's ready lists as from looking through every review", () => {
  const view = ({ df, shared }) => ({ df, shared: shared.map(([a, mine]) => [a.id, [...mine].sort()]).sort((x, y) => order(x[0], y[0])) });
  for (const tags of [["art rock"], ["electronic", "hip hop"], ["odd|tag"], ["no such tag"], []]) {
    const wanted = new Set(tags);
    assert.deepEqual(view(sharedTags(through(RAW), wanted)), view(sharedTags(plain(RAW), wanted)), tags.join());
  }
  const { df, shared } = sharedTags(through(RAW), new Set(["electronic"]));
  assert.deepEqual(df, { electronic: 2 }); // "electronic" and "Electronic"; the double post's tags don't count
  assert.deepEqual(shared.map(([a]) => a.id), ["a1", "a6"]);
});

test("anything that is not a packed archive of this format is refused, so the Worker reads archive.json", () => {
  const d = JSON.parse(JSON.stringify(pack(RAW)));
  assert.equal(unpack(null), null);
  assert.equal(unpack([]), null);
  assert.equal(unpack(RAW), null);
  assert.equal(unpack({ ...d, v: FORMAT + 1 }), null);
  assert.equal(unpack({ ...d, n: d.n + 1 }), null);
  assert.equal(unpack({ ...d, c: { ...d.c, album: d.c.album.slice(1) } }), null);
  assert.equal(unpack({ ...d, c: { ...d.c, ak: undefined } }), null);
  assert.equal(unpack({ ...d, t: null }).tags, null); // without the tag lists it still reads; «похожие» looks through the reviews
  assert.deepEqual(pack(null).c.id, []);
  assert.equal(through([]).data.length, 0);
});

test("order sorts dates and ids as plain strings", () => {
  assert.deepEqual(["2020-01-01", "2016-05-10", "2019-07-01"].sort(order), ["2016-05-10", "2019-07-01", "2020-01-01"]);
  assert.equal(order("a", "a"), 0);
});
