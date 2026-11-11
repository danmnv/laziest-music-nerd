// How the Worker reads the archive: the compact copy first, archive.json when the copy is missing or unreadable, and
// no second parse while GitHub says the file is still the same (ETag).
import { test, mock } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";
import { pack } from "../src/archive.mjs";

const review = (id, album) => ({ id, url: `https://tnd/${id}`, published: "2020-01-01", artist_name: "Radiohead", album, score: 9, genres: ["art rock"] });
const db = new DatabaseSync(":memory:");
db.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
db.prepare("INSERT INTO users (user_id, started_at) VALUES (1, '2026-10-31')").run();
db.prepare("INSERT INTO settings (key, value) VALUES ('menu:1', '4')").run();
const DB = {
  async batch(statements) { const out = []; for (const st of statements) out.push(await st.run()); return out; },
  prepare(sql) {
    let args = [];
    const st = {
      bind(...a) { args = a; return st; },
      async first() { return db.prepare(sql).get(...args) ?? null; },
      async all() { return { results: db.prepare(sql).all(...args) }; },
      async run() { return { meta: { changes: db.prepare(sql).run(...args).changes } }; },
    };
    return st;
  },
};
const env = { DB, WEBHOOK_SECRET: "w", ACTIONS_SECRET: "a", BOT_USERNAME: "bot", CHANNEL: "@chan", TELEGRAM_BOT_TOKEN: "t",
              DATA_URL: "https://data/reviews.json", SITE_URL: "https://site", OWNER_ID: "1" };

let files = {}; // name -> { body, etag, status } as GitHub would answer now
let asked = [], sent = [];
globalThis.fetch = async (url, opts) => {
  url = String(url);
  if (url.startsWith("https://api.telegram.org/")) {
    sent.push(JSON.parse(opts.body));
    return new Response(JSON.stringify({ ok: true, result: { message_id: 500 + sent.length } }));
  }
  const name = url.split("/").pop();
  asked.push(name);
  const f = files[name];
  if (!f) return new Response("not found", { status: 404 });
  return new Response(f.body, { status: f.status || 200, headers: f.etag ? { ETag: f.etag } : {} });
};

// the bot's answer to a typed search, and which data files it asked for
async function search(text) {
  asked = [];
  sent = [];
  const ps = [];
  await worker.fetch(new Request("https://w/tg", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "w" },
    body: JSON.stringify({ message: { message_id: 9, chat: { id: 1, type: "private" }, from: { id: 1 }, text } }) }), env, { waitUntil: (p) => ps.push(p) });
  await Promise.all(ps);
  return { said: JSON.stringify(sent), asked: asked.filter((n) => n.startsWith("archive")) };
}

const MIN = 60e3;

// One test: the Worker keeps the archive in memory between presses, so the steps follow each other on one clock.
test("the compact copy first; archive.json as the fallback; no second parse of an unchanged file", async () => {
  mock.timers.enable({ apis: ["Date"], now: Date.UTC(2026, 10, 11, 12) });
  const packed = (list) => JSON.stringify(pack(list));

  // 1. the copy is there: archive.json is not asked for at all
  files = { "archive.min.json": { body: packed([review("k", "Kid A")]), etag: 'W/"one"' }, "archive.json": { body: JSON.stringify([review("z", "Wrong File")]) } };
  let r = await search("radiohead");
  assert.match(r.said, /Kid A/);
  assert.deepEqual(r.asked, ["archive.min.json"]);

  // 2. within 10 minutes nothing is asked again
  files["archive.min.json"] = { body: packed([review("b", "The Bends")]), etag: 'W/"two"' };
  mock.timers.tick(9 * MIN);
  r = await search("radiohead");
  assert.match(r.said, /Kid A/);
  assert.deepEqual(r.asked, []);

  // 3. later the file is asked for again; a new ETag means new content
  mock.timers.tick(2 * MIN);
  r = await search("radiohead");
  assert.match(r.said, /The Bends/);
  assert.deepEqual(r.asked, ["archive.min.json"]);

  // 4. the same ETag: the copy in memory stays and the body is not read (it would not even parse here)
  files["archive.min.json"] = { body: "not json at all", etag: 'W/"two"' };
  mock.timers.tick(11 * MIN);
  r = await search("radiohead");
  assert.match(r.said, /The Bends/);
  assert.deepEqual(r.asked, ["archive.min.json"]);

  // 5. an unreadable copy (new ETag): archive.json is read instead
  files = { "archive.min.json": { body: "not json at all", etag: 'W/"three"' }, "archive.json": { body: JSON.stringify([review("o", "OK Computer"), { ...review("o2", "OK Computer"), dup_of: "o" }]) } };
  mock.timers.tick(11 * MIN);
  r = await search("radiohead");
  assert.match(r.said, /OK Computer/);
  assert.deepEqual(r.asked, ["archive.min.json", "archive.json"]);

  // 6. a copy in a format this code doesn't know: archive.json again, not a guess
  files["archive.min.json"] = { body: JSON.stringify({ ...pack([review("a", "Amnesiac")]), v: 99 }), etag: 'W/"four"' };
  files["archive.json"] = { body: JSON.stringify([review("h", "Hail to the Thief")]) };
  mock.timers.tick(11 * MIN);
  r = await search("radiohead");
  assert.match(r.said, /Hail to the Thief/);
  assert.deepEqual(r.asked, ["archive.min.json", "archive.json"]);

  // 7. no copy at all (before the first check run writes it): archive.json; and a copy with the ETag seen in step 5
  //    is parsed again, because what is in memory now came from archive.json
  delete files["archive.min.json"];
  mock.timers.tick(11 * MIN);
  r = await search("radiohead");
  assert.match(r.said, /Hail to the Thief/);
  files["archive.min.json"] = { body: packed([review("r", "In Rainbows")]), etag: 'W/"four"' };
  mock.timers.tick(11 * MIN);
  r = await search("radiohead");
  assert.match(r.said, /In Rainbows/);

  // 8. GitHub is down: what is in memory keeps answering
  files = {};
  mock.timers.tick(11 * MIN);
  r = await search("radiohead");
  assert.match(r.said, /In Rainbows/);
  mock.timers.reset();
});
