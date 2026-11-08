import { test } from "node:test";
import assert from "node:assert/strict";
import { topKey, topShard, topCritics, topAlbum } from "../src/top.mjs";

test("the key and file as lmn/aoty_top.py makes them", () => {
  assert.equal(topKey("Beyoncé", "Lemonade (Deluxe)"), "beyonce--lemonade");
  assert.equal(topKey("Simon & Garfunkel", "“Bookends”"), "simonandgarfunkel--bookends");
  assert.equal(topShard("beyonce--lemonade"), "be");
  assert.equal(topShard("m--m"), "m-");
  assert.equal(topShard("ものんくる--x"), "__"); // other scripts share one file
});

test("critics: three outlets, then AOTY's score", () => {
  assert.deepEqual(topCritics({ s: 81, c: [["Pitchfork", "8/10"], ["NME", "4/5"], ["Mojo", "4/5"], ["Uncut", "8/10"]] }),
    ["Pitchfork 8/10", "NME 4/5", "Mojo 4/5", "AOTY 81/100"]);
  assert.deepEqual(topCritics({}), []);
});

test("the album from the site's file; none when the file or the album isn't there", async () => {
  const get = async (u) => (u === "https://site/u/be.json"
    ? new Response(JSON.stringify({ "beyonce--lemonade": { s: 92 } })) : new Response("", { status: 404 }));
  assert.deepEqual(await topAlbum("https://site", "Beyoncé", "Lemonade", get), { s: 92 });
  assert.equal(await topAlbum("https://site", "Beyoncé", "Renaissance", get), null);
  assert.equal(await topAlbum("https://site", "Kanye West", "Ye", get), null);
});
