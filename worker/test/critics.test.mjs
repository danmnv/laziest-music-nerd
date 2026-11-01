import { test } from "node:test";
import assert from "node:assert/strict";
import { criticsText } from "../src/critics.mjs";

test("critics lines escape the Wikipedia link for an HTML attribute", () => {
  assert.equal(criticsText(null), "");
  assert.equal(criticsText({ crit: ["Metacritic 91"], sales: [], wp_url: 'https://en.wikipedia.org/wiki/A"B' }),
    '\nКритики: Metacritic 91 (<a href="https://en.wikipedia.org/wiki/A&quot;B">Википедия</a>)');
  assert.equal(criticsText({ crit: [], sales: ["US #1"], wp_url: "https://w/x" }), '\nЧарты и продажи: US #1 (<a href="https://w/x">Википедия</a>)');
  assert.equal(criticsText({ contested: "Фантано 3/10, критики 8/10 (Metacritic)", crit: ["Metacritic 80"], sales: [], wp_url: "https://w/x" }),
    '\n⚡ Спорно: Фантано 3/10, критики 8/10 (Metacritic)\nКритики: Metacritic 80 (<a href="https://w/x">Википедия</a>)');
});

test("a score written as {{Rating|4.|5}} reads as 4/5, as in lmn/ratings.py", async () => {
  const { clean } = await import("../src/wiki.mjs");
  assert.equal(clean("{{Rating|4.|5}}"), "4/5");
  assert.equal(clean("{{rating|3.5|5}}"), "3.5/5");
});

test("Fantano's lists come first, as links to the videos", () => {
  const t = criticsText({ lists: [{ text: "№1 из 9 в «Radiohead: от худшего к лучшему» (2017)", url: "https://www.youtube.com/watch?v=uu8&t=984" },
    { text: "топ-50 альбомов 2017 года", url: "https://youtu.be/yu" }], crit: ["Metacritic 91"], wp_url: "https://en.wikipedia.org/wiki/X" });
  assert.equal(t, '\n🏆 <a href="https://www.youtube.com/watch?v=uu8&amp;t=984">№1 из 9 в «Radiohead: от худшего к лучшему» (2017)</a> · ' +
    '<a href="https://youtu.be/yu">топ-50 альбомов 2017 года</a>\nКритики: Metacritic 91 (<a href="https://en.wikipedia.org/wiki/X">Википедия</a>)');
});
