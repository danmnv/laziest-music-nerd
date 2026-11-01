// The follow feature end to end against an in-memory SQLite standing in for D1 and a fake Telegram.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";

const OWNER = 1, OTHER = 2;
const ARCHIVE = [
  { id: "k", url: "https://tnd/kid-a", published: "2020-01-01", artist_name: "Radiohead", album: "Kid A", score: 10, genres: ["art rock"] },
  { id: "p", url: "https://tnd/pool", published: "2016-05-10", artist_name: "Radiohead", album: "A Moon Shaped Pool", score: 8, video_id: "vidvidvid01" },
  { id: "x", url: "https://tnd/x", published: "2011-01-01", artist_name: "Obscure", album: "Nothing", score: null },
];
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
    if (String(url).endsWith("archive.json")) return new Response(JSON.stringify(ARCHIVE));
    if (String(url).startsWith("https://api.deezer.com/search/album")) {
      return new Response(JSON.stringify({ data: [
        { id: 9, title: "Kid A (Remastered)", artist: { name: "Radiohead" }, cover_xl: "https://cdn/kida.jpg", nb_tracks: 10, link: "https://www.deezer.com/album/9" }] }));
    }
    if (String(url).startsWith("https://api.deezer.com/album/9")) return new Response(JSON.stringify({ duration: 2994, release_date: "2000-10-02" }));
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

test("typing a name in the private chat searches Fantano's archive", async () => {
  await say(OWNER, "radiohead");
  const list = calls.find((c) => c.method === "sendMessage");
  assert.equal(list.text, "Нашёл 2:");
  assert.deepEqual(list.reply_markup.inline_keyboard.map((r) => r[0].callback_data), ["a:k", "a:p"]);
  assert.match(list.reply_markup.inline_keyboard[0][0].text, /🟢 10\/10 · Radiohead — Kid A · обзор 2020/);
  calls = [];
  await say(OWNER, "nothing like this");
  assert.match(calls[0].text, /Не нашёл обзора Фантано/);
});

test("one hit is sent as a full card: cover, length, all services, marks and follow", async () => {
  await say(OWNER, "kid a");
  const c = calls.find((x) => x.method === "sendPhoto");
  assert.equal(c.photo, "https://cdn/kida.jpg");
  assert.match(c.caption, /<b>Radiohead — Kid A<\/b> \(2000\)\n🟢 10\/10 · art rock · 10 треков · 50 мин$/);
  const btns = c.reply_markup.inline_keyboard.flat();
  assert.ok(btns.some((b) => b.text === "Все платформы" && b.url === "https://album.link/https://www.deezer.com/album/9"));
  assert.ok(btns.some((b) => b.callback_data === "m:k:done"));
  assert.ok(btns.some((b) => b.callback_data === "f:k"));
  await press(OWNER, "f:k"); // an old review the bot never posted a card for
  assert.match(answers().at(-1).text, /Ты следишь за Radiohead/);
});

test("without a Deezer match the card is text with Google instead of all services", async () => {
  await press(OWNER, "a:x");
  const c = calls.find((x) => x.method === "sendMessage" && /Obscure/.test(x.text));
  assert.match(c.text, /⚪ без оценки · обзор 2011/);
  assert.ok(c.reply_markup.inline_keyboard.flat().some((b) => b.text === "🔎 Google"));
});

test("random pick is a full card too", async () => {
  await say(OWNER, "🎲 Случайный из архива");
  const c = calls.find((x) => x.method === "sendPhoto" || (x.method === "sendMessage" && /Случайный/.test(x.text)));
  const body = c.caption || c.text;
  assert.match(body, /^🎲 Случайный из архива:\n\n<b>Radiohead — /);
  assert.ok(c.reply_markup.inline_keyboard.flat().some((b) => b.callback_data && b.callback_data.startsWith("f:")));
});
