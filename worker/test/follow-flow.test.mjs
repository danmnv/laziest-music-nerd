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

const [KIDA, BENDS, OKNOTOK, PABLO, TKOL, LUNG, UNDATED, AMNESIAC] = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `0000000${n}-0000-4000-8000-000000000000`);
let mbDown = false;

beforeEach(() => {
  mbDown = false;
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
    if (String(url).endsWith("reviews.json")) return new Response(JSON.stringify([{ id: "old1", artist_name: "Shame", artist: { mbid: "S" } }, { id: "rk", artist_name: "Radiohead", artist: { mbid: "R" } }]));
    if (String(url).endsWith("archive.json")) return new Response(JSON.stringify(ARCHIVE));
    if (String(url) === "https://site/rt/k.json") {
      return new Response(JSON.stringify({ crit: ["Metacritic 91", "Pitchfork 10/10"], sales: ["US #1", "UK #1"], wp_url: "https://en.wikipedia.org/wiki/Kid_A",
        brief: "Radiohead уходят в электронику.", blurb: "Not shown when there is a brief.", moods: ["для работы за столом", "не то"] }));
    }
    if (String(url) === "https://site/wtb.json") return new Response(JSON.stringify([{ artist: "Radiohead", video_id: "uu8sC7YDOZg", date: "2017-04-17" }]));
    if (String(url) === "https://site/rt/p.json") {
      return new Response(JSON.stringify({ crit: [], sales: [], blurb: "Radiohead return & shine.", fav: ["DAYDREAMING", "TRUE LOVE WAITS"], fav_play: true }));
    }
    if (String(url).startsWith("https://site/rt/")) return new Response("not found", { status: 404 });
    if (String(url).startsWith("https://musicbrainz.org/") && mbDown) return new Response("busy", { status: 503 });
    if (String(url).startsWith("https://musicbrainz.org/ws/2/release-group?artist=R&") && String(url).includes("offset=100")) {
      return new Response(JSON.stringify({ "release-group-count": 101, "release-groups": [
        { id: AMNESIAC, title: "Amnesiac", "first-release-date": "2001-06-04", "primary-type": "Album", "secondary-types": [] }] }));
    }
    if (String(url).startsWith("https://musicbrainz.org/ws/2/release-group?artist=R&")) {
      const rg = (id, title, date, primary, second = []) => ({ id, title, "first-release-date": date, "primary-type": primary, "secondary-types": second });
      return new Response(JSON.stringify({ "release-group-count": 101, "release-groups": [
        rg(KIDA, "Kid A", "2000-10-02", "Album"),
        rg(BENDS, "The Bends", "1995-03-13", "Album"),
        rg(OKNOTOK, "OK Computer OKNOTOK 1997 2017", "2017-06-23", "Album", ["Compilation"]),
        rg(PABLO, "Pablo Honey", "1993-02-22", "Album"),
        rg(TKOL, "TKOL RMX 1234567", "2011-09-16", "Album", ["Remix"]),
        rg(LUNG, "My Iron Lung", "1994-09-26", "EP"),
        rg(UNDATED, "Bootleg", "", "Album")] }));
    }
    if (String(url).startsWith(`https://musicbrainz.org/ws/2/release-group/${BENDS}?inc=artist-credits`)) {
      return new Response(JSON.stringify({ id: BENDS, title: "The Bends", "first-release-date": "1995-03-13", "primary-type": "Album", "secondary-types": [],
        "artist-credit": [{ name: "Radiohead" }] }));
    }
    if (String(url).startsWith("https://api.deezer.com/search/album") && String(url).includes("nothing")) return new Response(JSON.stringify({ data: [] }));
    if (String(url).startsWith("https://api.deezer.com/search/album") && String(url).toLowerCase().includes("bends")) {
      return new Response(JSON.stringify({ data: [{ id: 20, title: "The Bends", artist: { name: "Radiohead" }, record_type: "album", cover_xl: "https://cdn/bends.jpg", nb_tracks: 12, link: "https://www.deezer.com/album/20" }] }));
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
    if (String(url).startsWith("https://api.deezer.com/album/9/tracks")) {
      return new Response(JSON.stringify({ data: [
        { title: "Everything in Its Right Place", rank: 700, preview: "https://cdn/p1.mp3", artist: { name: "Radiohead" } },
        { title: "Kid A", rank: 500, preview: "https://cdn/p2.mp3", artist: { name: "Radiohead" } },
        { title: "Idioteque", rank: 900, preview: "https://cdn/p3.mp3", artist: { name: "Radiohead" } },
        { title: "Motion Picture Soundtrack", rank: 100, preview: "https://cdn/p4.mp3", artist: { name: "Radiohead" } },
        { title: "No Preview", rank: 999, preview: "", artist: { name: "Radiohead" } }] }));
    }
    if (String(url).startsWith("https://api.deezer.com/album/20/tracks")) {
      return new Response(JSON.stringify({ data: [{ title: "Fake Plastic Trees", rank: 800, preview: "https://cdn/b1.mp3", artist: { name: "Radiohead" } }] }));
    }
    if (String(url).startsWith("https://api.deezer.com/album/20")) {
      return new Response(JSON.stringify({ id: 20, title: "The Bends", artist: { name: "Radiohead" }, release_date: "1995-03-13", nb_tracks: 12,
        duration: 2928, record_type: "album", genres: { data: [{ name: "Alternative" }] }, cover_xl: "https://cdn/bends.jpg", link: "https://www.deezer.com/album/20" }));
    }
    if (String(url).startsWith("https://en.wikipedia.org/w/api.php") && String(url).includes("list=search")) {
      return new Response(JSON.stringify({ query: { search: [{ title: "Radiohead discography" }, { title: "The Bends" }] } }));
    }
    if (String(url).startsWith("https://en.wikipedia.org/w/api.php") && !String(url).includes("titles=The+Bends")) {
      return new Response(JSON.stringify({ query: { pages: [{ title: "Radiohead discography", revisions: [{ slots: { main: { content: "no infobox" } } }] }] } }));
    }
    if (String(url).startsWith("https://en.wikipedia.org/w/api.php")) {
      const text = "{{Infobox album\n| name = The Bends\n| type = studio\n| artist = [[Radiohead]]\n}}\n" +
        "{{Music ratings\n| rev1 = [[AllMusic]]\n| rev1score = {{Rating|5|5}}\n| rev2 = [[Pitchfork (website)|Pitchfork]]\n| rev2score = 10/10\n| rev3 = Some Blog\n| rev3score = 9/10\n}}\n" +
        "{{Album chart|Billboard200|88}}\n{{Album chart|UK2|4}}\n" +
        "{{Certification Table Entry|region=United Kingdom|award=Platinum|number=4}}\n{{Certification Table Entry|region=United Kingdom|award=Platinum|number=4}}\n";
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
  assert.deepEqual(list.reply_markup.inline_keyboard.map((r) => r[0].callback_data || r[0].url), ["a:k", "a:p", "da:k", "https://youtu.be/uu8sC7YDOZg"]);
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
  assert.match(c.caption, /<b>Radiohead — Kid A<\/b> \(2000\)\n🟢 10\/10 · art rock · 10 треков · 50 мин · 2-й из 2 обзоров артиста\n\n<b>Бриф:<\/b> Radiohead уходят в электронику\.\n/);
  assert.doesNotMatch(c.caption, /Not shown/); // the archive's brief (lmn/briefs.py) replaces Fantano's line
  assert.match(c.caption, /\nКритики: Metacritic 91 · Pitchfork 10\/10 \(<a href="https:\/\/en.wikipedia.org\/wiki\/Kid_A">Википедия<\/a>\)\nЧарты и продажи: US #1 · UK #1$/);
  const btns = c.reply_markup.inline_keyboard.flat();
  assert.ok(btns.some((b) => b.text === "Все платформы" && b.url === "https://album.link/https://www.deezer.com/album/9"));
  // the archive brief's mood guess: the channel card's vote, «другое» opens all four
  assert.match(c.caption, /\n<b>Когда слушать:<\/b> для работы за столом <i>\(догадка ИИ, поправь кнопками\)<\/i>/);
  assert.ok(btns.some((b) => b.text === "для работы за столом: да" && b.callback_data === "v:k:0:y"));
  assert.ok(btns.some((b) => b.text === "Настроение: другое" && b.callback_data === "mq:k"));
  assert.ok(!btns.some((b) => b.text === "🕒 Когда слушать?"));
  await press(OWNER, "v:k:0:y");
  assert.deepEqual({ ...db.prepare("SELECT review_id, mood, vote FROM mood_votes").get() }, { review_id: "k", mood: "для работы за столом", vote: "y" });
  assert.ok(btns.some((b) => b.text === "🔎 AOTY" && b.url === "https://www.albumoftheyear.org/search/?q=Radiohead%20Kid%20A"));
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
  assert.deepEqual(list.reply_markup.inline_keyboard.at(-2)[0], { text: "💿 Другие альбомы (без обзора Фантано)", callback_data: "da:k" });
  assert.deepEqual(list.reply_markup.inline_keyboard.at(-1)[0], { text: "🎬 Radiohead: от худшего к лучшему (2017)", url: "https://youtu.be/uu8sC7YDOZg" });
  calls = [];
  await press(OWNER, "da:k");
  const other = calls.find((c) => c.method === "sendMessage");
  assert.equal(other.text, "Radiohead — альбомы без обзора Фантано:");
  // studio albums newest first with the year of the first release, then EPs; reviewed Kid A and the undated one left out;
  // the compilation and the remixes wait behind their own button
  assert.deepEqual(other.reply_markup.inline_keyboard.map((r) => [r[0].text, r[0].callback_data]), [
    ["💿 Amnesiac · 2001", `mb:${AMNESIAC}`], // from the second page
    ["💿 The Bends · 1995", `mb:${BENDS}`],
    ["💿 Pablo Honey · 1993", `mb:${PABLO}`],
    ["💿 My Iron Lung · 1994 · EP", `mb:${LUNG}`],
    ["Ещё: концертные, сборники, ремиксы (2)", "dx:k"]]);
  calls = [];
  await press(OWNER, "dx:k");
  const extra = calls.find((c) => c.method === "sendMessage");
  assert.equal(extra.text, "Radiohead — концертные, сборники, ремиксы и прочее:");
  assert.deepEqual(extra.reply_markup.inline_keyboard.map((r) => [r[0].text, r[0].callback_data]), [
    ["💿 OK Computer OKNOTOK 1997 2017 · 2017 · сборник", `mb:${OKNOTOK}`],
    ["💿 TKOL RMX 1234567 · 2011 · ремиксы", `mb:${TKOL}`]]);
  calls = [];
  await press(OWNER, `mb:${BENDS}`);
  const c = calls.find((x) => x.method === "sendPhoto");
  assert.equal(c.photo, "https://cdn/bends.jpg");
  assert.equal(c.caption, '<b>Radiohead — The Bends</b> (1995)\n⚪ Фантано не обозревал · Alternative · 12 треков · 49 мин' +
    '\nКритики: Pitchfork 10/10 · AllMusic 5/5 (<a href="https://en.wikipedia.org/wiki/The_Bends">Википедия</a>)\nЧарты и продажи: US #88 · UK #4 · UK 4× Platinum');
  const btns = c.reply_markup.inline_keyboard.flat();
  assert.ok(btns.some((b) => b.text === "Все платформы" && b.url === "https://album.link/https://www.deezer.com/album/20"));
  assert.ok(btns.some((b) => b.callback_data === "f:k"));
  calls = [];
  mbDown = true; // MusicBrainz busy: the card is made from the list button's title and year
  await tgUpdate({ callback_query: { id: "q", from: { id: OWNER }, data: `mb:${BENDS}`, message: { message_id: 78, text: other.text, reply_markup: other.reply_markup } } });
  assert.match(calls.find((x) => x.method === "sendPhoto").caption, /^<b>Radiohead — The Bends<\/b> \(1995\)\n⚪ Фантано не обозревал · Alternative · 12 треков/);
  mbDown = false;
  calls = [];
  await press(OWNER, "dz:9"); // a reviewed album opened from Deezer gets the usual card
  assert.match(calls.find((x) => x.method === "sendPhoto").caption, /^<b>Radiohead — Kid A<\/b>/);
});

test("when MusicBrainz is down, the list comes from Deezer: albums only, the first edition's year", async () => {
  mbDown = true;
  await press(OWNER, "da:k");
  const other = calls.find((c) => c.method === "sendMessage");
  assert.equal(other.text, "Radiohead — альбомы без обзора Фантано:");
  // reviewed Kid A, the later Bends edition and the single are left out; newest first; no extras button
  assert.deepEqual(other.reply_markup.inline_keyboard.map((r) => [r[0].text, r[0].callback_data]),
    [["💿 OK Computer OKNOTOK 1997 2017 · 2017", "dz:22"], ["💿 The Bends · 1995", "dz:20"]]);
  calls = [];
  await press(OWNER, "dz:20");
  assert.match(calls.find((x) => x.method === "sendPhoto").caption, /^<b>Radiohead — The Bends<\/b> \(1995\)/);
});

test("an album without a review can be put off: it shows in «📌 Отложенные»", async () => {
  await press(OWNER, `mb:${BENDS}`);
  const card = calls.find((x) => x.method === "sendPhoto");
  const btns = card.reply_markup.inline_keyboard;
  assert.deepEqual(btns.find((r) => r[0].callback_data === `m:${BENDS}:later`).map((b) => b.text), ["• Отложить", "✓ Слушал", "✗ Не моё"]);
  assert.ok(btns.flat().some((b) => b.text === "🔎 Google"));
  await press(OWNER, `m:${BENDS}:later`);
  calls = [];
  await say(OWNER, "📌 Отложенные");
  const list = calls.find((c) => c.method === "sendMessage");
  assert.match(list.text, /^Отложено: 1\./);
  assert.deepEqual(list.reply_markup.inline_keyboard, [[{ text: "• Radiohead — The Bends", callback_data: `mb:${BENDS}` }]]);
});

test("a reviewed album: Fantano's line, favourites with a player on the site, n-th review, «Когда слушать?», put off", async () => {
  await press(OWNER, "a:p");
  const c = calls.find((x) => x.method === "sendPhoto" || (x.method === "sendMessage" && /Moon/.test(x.text)));
  const text = c.caption || c.text;
  assert.match(text, /1-й из 2 обзоров артиста\n\n💬 <i>Radiohead return &amp; shine\.<\/i>\n★ Любимые у Фантано: DAYDREAMING, TRUE LOVE WAITS/);
  const btns = c.reply_markup.inline_keyboard.flat();
  assert.ok(btns.some((b) => b.text === "🔔 Следить") && btns.some((b) => b.text === "📚 Все обзоры"));
  assert.ok(btns.some((b) => b.text === "▶ Любимые треки" && b.url === "https://site/r/p.html#fav"));
  assert.ok(!btns.some((b) => /Отрывки/.test(b.text)));
  calls = [];
  await press(OWNER, "mq:p");  // art rock, no AI guess: the genre's four, then «Другие варианты»
  const m = calls.find((x) => x.method === "sendMessage");
  assert.equal(m.text, "Когда лучше слушать <b>Radiohead — A Moon Shaped Pool</b>?");
  assert.deepEqual(m.reply_markup.inline_keyboard.map((row) => row.map((b) => b.text)),
    [["в наушниках, вдумчиво", "ночью"], ["когда злишься", "в дорогу"], ["Другие варианты"]]);
  assert.equal(m.reply_markup.inline_keyboard[0][0].callback_data, "vo:p:10");
  calls = [];
  await press(OWNER, "ma:p");
  const all = calls.find((x) => x.method === "editMessageText");
  assert.equal(all.reply_markup.inline_keyboard.flat().length, 14);
  await press(OWNER, "vo:p:4");
  calls = [];
  await press(OWNER, "mq:k");  // the archive brief's guess comes first, the genre's fill the rest
  assert.deepEqual(calls.find((x) => x.method === "sendMessage").reply_markup.inline_keyboard[0].map((b) => b.text),
    ["для работы за столом", "в наушниках, вдумчиво"]);
  assert.ok(db.prepare("SELECT 1 FROM mood_votes WHERE review_id='p' AND mood='в дорогу'").get());
  await press(OWNER, "m:k:later");
  calls = [];
  await say(OWNER, "📌 Отложенные");
  assert.deepEqual(calls.find((x) => x.method === "sendMessage").reply_markup.inline_keyboard, [[{ text: "• Radiohead — Kid A", callback_data: "a:k" }]]);
});

test("the 21-day reminder covers albums put off from the archive and without a review", async () => {
  await press(OWNER, `mb:${BENDS}`);
  await press(OWNER, `m:${BENDS}:later`);
  db.prepare("UPDATE marks SET later_at='2026-01-01T00:00:00Z'").run();
  calls = [];
  await worker.scheduled({ cron: "0 9 * * *", scheduledTime: Date.UTC(2026, 10, 3, 9) }, env, { waitUntil: (p) => p });
  await new Promise((r) => setTimeout(r, 50));
  const m = calls.find((c) => c.method === "sendMessage" && /Три недели назад/.test(c.text));
  assert.ok(m, "a reminder was sent");
  assert.match(m.text, /<b>Radiohead — The Bends<\/b>/);
  assert.deepEqual(m.reply_markup.inline_keyboard[0], [{ text: "✓ Слушал", callback_data: `m:${BENDS}:done` }, { text: "Открыть", callback_data: `mb:${BENDS}` }]);
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
