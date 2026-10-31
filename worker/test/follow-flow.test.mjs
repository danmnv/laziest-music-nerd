// The follow feature end to end against an in-memory SQLite standing in for D1 and a fake Telegram.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";

const OWNER = 1, OTHER = 2;
let db, calls, env;

function d1(sqlite) {
  return {
    prepare(sql) {
      let args = [];
      const st = {
        bind(...a) { args = a; return st; },
        async first() { return sqlite.prepare(sql).get(...args) ?? null; },
        async all() { return { results: sqlite.prepare(sql).all(...args) }; },
        async run() { return { meta: { changes: sqlite.prepare(sql).run(...args).changes } }; },
      };
      return st;
    },
  };
}

beforeEach(() => {
  db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  db.prepare("INSERT INTO users (user_id, started_at) VALUES (?, ?)").run(OWNER, "2026-10-31");
  calls = [];
  env = { DB: d1(db), WEBHOOK_SECRET: "w", ACTIONS_SECRET: "a", BOT_USERNAME: "bot", CHANNEL: "@chan", TELEGRAM_BOT_TOKEN: "t",
          DATA_URL: "https://data/reviews.json", SITE_URL: "https://site", OWNER_ID: String(OWNER) };
  globalThis.fetch = async (url, opts) => {
    if (String(url).startsWith("https://api.telegram.org/")) {
      calls.push({ method: String(url).split("/").pop(), ...JSON.parse(opts.body) });
      return new Response(JSON.stringify({ ok: true, result: { message_id: 500 + calls.length } }));
    }
    if (String(url).endsWith("list.json")) return new Response(JSON.stringify({ items: [] }));
    if (String(url).endsWith("reviews.json")) return new Response(JSON.stringify([{ id: "old1", artist_name: "Shame", artist: { mbid: "S" } }]));
    throw new Error("unexpected fetch " + url);
  };
});

async function tgUpdate(update) {
  const waits = [];
  await worker.fetch(new Request("https://w/tg", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "w" }, body: JSON.stringify(update) }),
    env, { waitUntil: (p) => waits.push(p) });
  await Promise.all(waits);
}
const press = (uid, data, message_id = 77) => tgUpdate({ callback_query: { id: "q", from: { id: uid }, data, message: { message_id } } });
const say = (uid, text) => tgUpdate({ message: { chat: { type: "private" }, from: { id: uid }, text } });
async function newReviews(reviews) {
  const r = await worker.fetch(new Request("https://w/api/new-reviews", { method: "POST", headers: { Authorization: "Bearer a" }, body: JSON.stringify({ reviews }) }),
    env, { waitUntil() {} });
  return r.json();
}
const card = (id, mbid = "H", msg = 123) => ({ id, artist_name: "HMLTD", mbid, album: "FANGS " + id, score: "🟡 5/10", msg });
const answers = () => calls.filter((c) => c.method === "answerCallbackQuery");

test("follow from a card, hear about the next review once, with a link to the channel post", async () => {
  await newReviews([card("r1")]);                     // the card goes out; nobody follows yet
  await press(OWNER, "f:r1");
  assert.match(answers().at(-1).text, /Ты следишь за HMLTD/);
  assert.ok(calls.some((c) => c.method === "sendMessage" && c.chat_id === OWNER && /Мои артисты/.test(c.text)), "first follow explains the list");
  calls = [];
  assert.deepEqual(await newReviews([card("r2", "H", 124)]), { ok: true, sent: 1 });
  const dm = calls.find((c) => c.method === "sendMessage");
  assert.equal(dm.chat_id, OWNER);
  assert.match(dm.text, /Новый обзор: <b>HMLTD — FANGS r2<\/b>, 🟡 5\/10/);
  assert.equal(dm.reply_markup.inline_keyboard[0][0].url, "https://t.me/chan/124");
  assert.equal(dm.disable_notification, undefined);
  assert.deepEqual(await newReviews([card("r2", "H", 124)]), { ok: true, sent: 0 }, "a retry doesn't message twice");
});

test("another artist with the same name (different MusicBrainz ID) is not announced", async () => {
  await newReviews([card("r1", "H")]);
  await press(OWNER, "f:r1");
  assert.equal((await newReviews([card("r2", "OTHER")])).sent, 0);
  assert.equal((await newReviews([card("r3", null)])).sent, 1, "without an ID on one side the name decides");
});

test("a second press stops following; older cards are found in reviews.json", async () => {
  await press(OWNER, "f:old1");
  assert.match(answers().at(-1).text, /Ты следишь за Shame/);
  await press(OWNER, "f:old1");
  assert.match(answers().at(-1).text, /Больше не следишь за Shame/);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM follows").get().n, 0);
});

test("someone who never started the bot is sent to it, and the follow is made there", async () => {
  await newReviews([card("r1")]);
  await press(OTHER, "f:r1");
  assert.equal(answers().at(-1).url, "https://t.me/bot?start=follow_r1");
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM follows").get().n, 0);
  await say(OTHER, "/start follow_r1");
  await say(OTHER, "/start follow_r1"); // starting again keeps the follow
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM follows WHERE user_id=?").get(OTHER).n, 1);
  assert.equal((await newReviews([card("r2")])).sent, 1);
});

test("the list in the private chat, and unfollowing from it", async () => {
  await newReviews([card("r1")]);
  await press(OWNER, "f:r1");
  await press(OWNER, "f:old1");
  calls = [];
  await say(OWNER, "🔔 Мои артисты");
  const list = calls.find((c) => c.method === "sendMessage");
  assert.match(list.text, /HMLTD[\s\S]*Shame/);
  const btn = list.reply_markup.inline_keyboard[0][0];
  assert.equal(btn.text, "✗ HMLTD");
  await press(OWNER, btn.callback_data, 900);
  const edit = calls.find((c) => c.method === "editMessageText" && c.message_id === 900);
  assert.doesNotMatch(edit.text, /HMLTD/);
  assert.match(edit.text, /Shame/);
  await press(OTHER, btn.callback_data); // someone else's follow id does nothing
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM follows").get().n, 1);
});

test("/api/new-reviews needs the Actions secret", async () => {
  const r = await worker.fetch(new Request("https://w/api/new-reviews", { method: "POST", body: "{}" }), env, { waitUntil() {} });
  assert.equal(r.status, 403);
});
