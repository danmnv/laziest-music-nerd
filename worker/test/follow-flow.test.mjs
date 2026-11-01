// The follow feature end to end against an in-memory SQLite standing in for D1 and a fake Telegram.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";

const OWNER = 1, OTHER = 2;
const ARCHIVE = [
  { id: "k", url: "https://tnd/kid-a", published: "2020-01-01", artist_name: "Radiohead", album: "Kid A", score: 10, genres: ["art rock"] },
  { id: "p", url: "https://tnd/pool", published: "2016-05-10", artist_name: "Radiohead", album: "A Moon Shaped Pool", score: 8, video_id: "vidvidvid01", genres: ["art rock"] },
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
    if (String(url).endsWith("state.json")) return new Response(JSON.stringify({ channel_pinned_id: 2 }));
    if (String(url).endsWith("list.json")) return new Response(JSON.stringify({ items: [] }));
    if (String(url).endsWith("reviews.json")) return new Response(JSON.stringify([{ id: "old1", artist_name: "Shame", artist: { mbid: "S" } }]));
    if (String(url).endsWith("archive.json")) return new Response(JSON.stringify(ARCHIVE));
    if (String(url) === "https://site/rt/k.json") {
      return new Response(JSON.stringify({ crit: ["Metacritic 91", "Pitchfork 10/10"], sales: ["US #1", "UK #1"], wp_url: "https://en.wikipedia.org/wiki/Kid_A" }));
    }
    if (String(url).startsWith("https://site/rt/")) return new Response("not found", { status: 404 });
    if (String(url).startsWith("https://api.deezer.com/search/album") && String(url).includes("nothing")) return new Response(JSON.stringify({ data: [] }));
    if (String(url).startsWith("https://api.deezer.com/search/album") && String(url).includes("bends")) {
      return new Response(JSON.stringify({ data: [{ id: 20, title: "The Bends", artist: { name: "Radiohead" }, record_type: "album" }] }));
    }
    if (String(url).startsWith("https://api.deezer.com/search/artist")) return new Response(JSON.stringify({ data: [{ id: 399, name: "Radiohead" }] }));
    if (String(url).startsWith("https://api.deezer.com/artist/399/albums")) {
      return new Response(JSON.stringify({ data: [
        { id: 9, title: "Kid A (Remastered)", release_date: "2000-10-02", record_type: "album" },
        { id: 20, title: "The Bends", release_date: "1995-03-13", record_type: "album" },
        { id: 21, title: "The Bends (Collector's Edition)", release_date: "2009-03-24", record_type: "album" },
        { id: 22, title: "OK Computer OKNOTOK 1997 2017", release_date: "2017-06-23", record_type: "album" },
        { id: 23, title: "Creep", release_date: "1992-09-21", record_type: "single" }] }));
    }
    if (String(url).startsWith("https://api.deezer.com/album/20")) {
      return new Response(JSON.stringify({ id: 20, title: "The Bends", artist: { name: "Radiohead" }, release_date: "1995-03-13", nb_tracks: 12,
        duration: 2928, record_type: "album", genres: { data: [{ name: "Alternative" }] }, cover_xl: "https://cdn/bends.jpg", link: "https://www.deezer.com/album/20" }));
    }
    if (String(url).startsWith("https://en.wikipedia.org/w/api.php")) {
      const text = "{{Infobox album\n| name = The Bends\n| type = studio\n| artist = [[Radiohead]]\n}}\n" +
        "{{Music ratings\n| rev1 = [[AllMusic]]\n| rev1score = {{Rating|5|5}}\n| rev2 = [[Pitchfork (website)|Pitchfork]]\n| rev2score = 10/10\n| rev3 = Some Blog\n| rev3score = 9/10\n}}\n" +
        "{{Album chart|Billboard200|88}}\n{{Album chart|UK2|4}}\n";
      return new Response(JSON.stringify({ query: { pages: [{ index: 1, title: "The Bends", revisions: [{ slots: { main: { content: text } } }] }] } }));
    }
    if (String(url).startsWith("https://api.deezer.com/search/album")) {
      return new Response(JSON.stringify({ data: [
        { id: 9, title: "Kid A (Remastered)", artist: { name: "Radiohead" }, cover_xl: "https://cdn/kida.jpg", nb_tracks: 10, link: "https://www.deezer.com/album/9" }] }));
    }
    if (String(url).startsWith("https://api.deezer.com/album/9")) return new Response(JSON.stringify({ id: 9, title: "Kid A (Remastered)", artist: { name: "Radiohead" }, duration: 2994, release_date: "2000-10-02" }));
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
  assert.equal(list.text, "Radiohead — 2 обзора Фантано:");
  assert.deepEqual(list.reply_markup.inline_keyboard.map((r) => r[0].callback_data), ["a:k", "a:p", "da:k"]);
  assert.equal(list.reply_markup.inline_keyboard[0][0].text, "🟢 10/10 · Kid A · обзор 2020");
  calls = [];
  await press(OWNER, "ar:p"); // "Все обзоры артиста" on any of their cards
  assert.equal(calls.find((c) => c.method === "sendMessage").text, "Radiohead — 2 обзора Фантано:");
  calls = [];
  await say(OWNER, "nothing like this");
  assert.match(calls[0].text, /Не нашёл обзора Фантано/);
});

test("one hit is sent as a full card: cover, length, all services, marks and follow", async () => {
  await say(OWNER, "kid a");
  const c = calls.find((x) => x.method === "sendPhoto");
  assert.equal(c.photo, "https://cdn/kida.jpg");
  assert.match(c.caption, /<b>Radiohead — Kid A<\/b> \(2000\)\n🟢 10\/10 · art rock · 10 треков · 50 мин\n/);
  assert.match(c.caption, /\nКритики: Metacritic 91 · Pitchfork 10\/10 \(<a href="https:\/\/en.wikipedia.org\/wiki\/Kid_A">Википедия<\/a>\)\nЧарты и продажи: US #1 · UK #1$/);
  const btns = c.reply_markup.inline_keyboard.flat();
  assert.ok(btns.some((b) => b.text === "Все платформы" && b.url === "https://album.link/https://www.deezer.com/album/9"));
  assert.ok(btns.some((b) => b.callback_data === "m:k:done"));
  assert.ok(btns.some((b) => b.callback_data === "f:k"));
  assert.ok(btns.some((b) => b.callback_data === "ar:k"));
  await press(OWNER, "f:k"); // an old review the bot never posted a card for
  assert.match(answers().at(-1).text, /Ты следишь за Radiohead/);
});

test("without a Deezer match the card is text with Google instead of all services", async () => {
  await press(OWNER, "a:x");
  const c = calls.find((x) => x.method === "sendMessage" && /Obscure/.test(x.text));
  assert.match(c.text, /⚪ без оценки · обзор 2011/);
  assert.ok(c.reply_markup.inline_keyboard.flat().some((b) => b.text === "🔎 Google"));
});

test("an artist's albums without Fantano's review, and a card for one of them", async () => {
  await say(OWNER, "radiohead");
  const list = calls.find((c) => c.method === "sendMessage");
  assert.deepEqual(list.reply_markup.inline_keyboard.at(-1)[0], { text: "💿 Другие альбомы (без обзора Фантано)", callback_data: "da:k" });
  calls = [];
  await press(OWNER, "da:k");
  const other = calls.find((c) => c.method === "sendMessage");
  assert.equal(other.text, "Radiohead — альбомы без обзора Фантано (по данным Deezer):");
  // reviewed Kid A, the later Bends edition and the single are left out; newest first
  assert.deepEqual(other.reply_markup.inline_keyboard.map((r) => [r[0].text, r[0].callback_data]),
    [["💿 OK Computer OKNOTOK 1997 2017 · 2017", "dz:22"], ["💿 The Bends · 1995", "dz:20"]]);
  calls = [];
  await press(OWNER, "dz:20");
  const c = calls.find((x) => x.method === "sendPhoto");
  assert.equal(c.photo, "https://cdn/bends.jpg");
  assert.equal(c.caption, '<b>Radiohead — The Bends</b> (1995)\n⚪ Фантано не обозревал · Alternative · 12 треков · 49 мин' +
    '\nКритики: Pitchfork 10/10 · AllMusic 5/5 (<a href="https://en.wikipedia.org/wiki/The_Bends">Википедия</a>)\nЧарты и продажи: US #88 · UK #4');
  const btns = c.reply_markup.inline_keyboard.flat();
  assert.ok(btns.some((b) => b.text === "Все платформы" && b.url === "https://album.link/https://www.deezer.com/album/20"));
  assert.ok(btns.some((b) => b.callback_data === "f:k"));
  calls = [];
  await press(OWNER, "dz:9"); // a reviewed album opened from Deezer gets the usual card
  assert.match(calls.find((x) => x.method === "sendPhoto").caption, /^<b>Radiohead — Kid A<\/b>/);
});

test("a search without a review offers what Deezer has", async () => {
  await say(OWNER, "the bends");
  const m = calls.find((c) => c.method === "sendMessage");
  assert.equal(m.text, "Обзора Фантано по запросу «the bends» нет. Нашёл в Deezer:");
  assert.deepEqual(m.reply_markup.inline_keyboard[0][0], { text: "💿 Radiohead — The Bends", callback_data: "dz:20" });
});

test("random pick is a full card too", async () => {
  await say(OWNER, "🎲 Случайный из архива");
  const c = calls.find((x) => x.method === "sendPhoto" || (x.method === "sendMessage" && /Случайный/.test(x.text)));
  const body = c.caption || c.text;
  assert.match(body, /^🎲 Случайный из архива:\n\n<b>Radiohead — /);
  assert.ok(c.reply_markup.inline_keyboard.flat().some((b) => b.callback_data && b.callback_data.startsWith("f:")));
});

test("a button press is answered before the slow follow-ups (similar albums, a full card)", async () => {
  await say(OWNER, "/start");
  calls = [];
  await press(OWNER, "m:k:done"); // Kid A as listened: three similar cards follow
  const first = calls.findIndex((c) => c.method === "answerCallbackQuery");
  const firstCard = calls.findIndex((c) => c.method === "sendPhoto" || (c.method === "sendMessage" && /Понравилось/.test(c.text || "")));
  assert.ok(first >= 0 && firstCard > first, `answer at ${first}, first similar message at ${firstCard}`);
  assert.equal(answers().length, 1, "answered exactly once");
  calls = [];
  await press(OWNER, "a:k");
  assert.equal(calls[0].method, "answerCallbackQuery");
  assert.equal(answers().length, 1);
});
