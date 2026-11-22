import { test } from "node:test";
import assert from "node:assert/strict";
import { topKey, topShard, topCritics, topAlbum, fullName, searchVariants, variantsOf, matchVariant } from "../src/top.mjs";

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

test("same-title releases match explicit editions or a unique year, never the first row by default", () => {
  const variants = {
    "1": { a: "Weezer", t: "Weezer (Blue Album)", d: "1994-05-10" },
    "2": { a: "Weezer", t: "Weezer (Green Album)", d: "2001-05-15" },
    "3": { a: "John Coltrane", t: "Ascension [Edition I]", d: "1966-02-02" },
    "4": { a: "John Coltrane", t: "Ascension [Edition II]", d: "1966-02" },
    "5": { a: "!!!", t: "Myth Takes", d: "2007-03-06" },
    "6": { a: "Justice", t: "†", aliases: ["Cross"], d: "2007-06-11" },
    "7": { a: "Taylor Swift", t: "Fearless", d: "2008-11-11" },
  };
  const weezer = variantsOf(variants, "Weezer", "Weezer");
  assert.equal(matchVariant(weezer, "Weezer", "1994")[0], "1");
  assert.equal(matchVariant(weezer, "Weezer", "2001")[0], "2");
  assert.equal(matchVariant(weezer, "Weezer", ""), null);
  assert.equal(matchVariant(weezer, "Weezer (Blue Album)", "")[0], "1");
  assert.equal(matchVariant(weezer, "Weezer (Black Album)", "1994"), null);
  assert.equal(matchVariant(weezer, "Weezer (Green Album)", "1994"), null);
  assert.equal(matchVariant(variantsOf(variants, "John Coltrane", "Ascension"), "Ascension", "1966"), null);
  assert.deepEqual(searchVariants(variants, "Weezer Green Album").map(([id]) => id), ["2"]);
  assert.deepEqual(searchVariants(variants, "Weezer 1994").map(([id]) => id), ["1"]);
  assert.deepEqual(searchVariants(variants, "John Coltrane Ascension").map(([id]) => id), ["3", "4"]);
  assert.deepEqual(searchVariants(variants, "!!!").map(([id]) => id), ["5"]);
  assert.notEqual(fullName("!!!"), fullName("+/-"));
  assert.equal(matchVariant(variantsOf(variants, "Justice", "Cross"), "Cross", "2007")[0], "6");
  const fearless = variantsOf(variants, "Taylor Swift", "Fearless");
  assert.equal(matchVariant(fearless, "Fearless", ""), null);
  assert.equal(matchVariant(fearless, "Fearless", "2021"), null);
});
