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
    async batch(statements) { const out = []; for (const st of statements) out.push(await st.run()); return out; },
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
let longBrief = null; // a brief too long for a photo's caption
let rtMoods = null; // the archive brief's mood guess for Kid A, when a test needs another
let rtAl = null; // the album as checked from Actions (data/albums.json), in Kid A's rt file
let topU = null; // the site's u/ra.json (the owner's AOTY table, lmn/aoty_top.py)
let pinnedNow = null; // what getChat says is pinned in a private chat
let freshAlbums = []; // albums Deezer lists for Radiohead on top of the old ones
let fetched = []; // every URL the Worker asked outside Telegram

beforeEach(() => {
  mbDown = false;
  longBrief = null;
  rtMoods = null;
  rtAl = null;
  topU = null;
  pinnedNow = null;
  freshAlbums = [];
  db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  db.prepare("INSERT INTO users (user_id, started_at) VALUES (?, ?)").run(OWNER, "2026-10-31");
  db.prepare("INSERT INTO settings (key, value) VALUES (?, ?)").run(`menu:${OWNER}`, "4"); // has the current keyboard
  calls = [];
  env = { DB: d1(db), WEBHOOK_SECRET: "w", ACTIONS_SECRET: "a", BOT_USERNAME: "bot", CHANNEL: "@chan", TELEGRAM_BOT_TOKEN: "t",
          DATA_URL: "https://data/reviews.json", SITE_URL: "https://site", OWNER_ID: String(OWNER) };
  fetched = [];
  globalThis.fetch = async (url, opts) => {
    if (!String(url).startsWith("https://api.telegram.org/")) fetched.push(String(url));
    if (String(url).startsWith("https://api.telegram.org/")) {
      calls.push({ method: String(url).split("/").pop(), ...JSON.parse(opts.body) });
      if (String(url).endsWith("/getChat")) return new Response(JSON.stringify({ ok: true, result: pinnedNow ? { pinned_message: { message_id: pinnedNow } } : {} }));
      return new Response(JSON.stringify({ ok: true, result: { message_id: 500 + calls.length } }));
    }
    if (String(url).endsWith("state.json")) return new Response(JSON.stringify({ channel_pinned_id: 2 }));
    if (String(url).endsWith("list.json")) return new Response(JSON.stringify({ items: [] }));
    if (String(url).endsWith("reviews.json")) return new Response(JSON.stringify([{ id: "old1", artist_name: "Shame", artist: { mbid: "S" } }, { id: "rk", artist_name: "Radiohead", artist: { mbid: "R" } }]));
    if (String(url).endsWith("archive.json")) return new Response(JSON.stringify(ARCHIVE));
    if (String(url) === "https://site/rt/k.json") {
      return new Response(JSON.stringify({ crit: ["Metacritic 91", "Pitchfork 10/10"], sales: ["US #1", "UK #1"], wp_url: "https://en.wikipedia.org/wiki/Kid_A", video_id: "kidavideo01", bc: "https://radiohead.bandcamp.com/album/kid-a",
        brief: longBrief || "Radiohead уходят в электронику.", blurb: "Not shown when there is a brief.", moods: rtMoods || ["для работы за столом", "не то"],
        who: "британская рок-группа, четвёртый альбом", ...(rtAl ? { al: rtAl } : {}) }));
    }
    if (String(url) === "https://site/u/ra.json" && topU) return new Response(JSON.stringify(topU));
    if (String(url).startsWith("https://site/u/")) return new Response("not found", { status: 404 });
    if (String(url) === "https://site/wtb.json") return new Response(JSON.stringify([{ artist: "Radiohead", video_id: "uu8sC7YDOZg", date: "2017-04-17" }]));
    if (String(url) === "https://site/rt/p.json") {
      return new Response(JSON.stringify({ crit: [], sales: [], blurb: "Radiohead return & shine.", fav: ["DAYDREAMING", "TRUE LOVE WAITS"], fav_play: true,
        apple: "https://music.apple.com/us/album/a-moon-shaped-pool/5" }));
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
      return new Response(JSON.stringify({ data: [...freshAlbums,
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
    if (String(url) === "https://api.deezer.com/album/30") {
      return new Response(JSON.stringify({ id: 30, title: "Wall of Eyes", artist: { name: "Radiohead" }, release_date: "2026-11-02", nb_tracks: 8,
        duration: 2700, record_type: "album", genres: { data: [{ name: "Alternative" }] }, cover_xl: "https://cdn/woe.jpg" }));
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
        { id: 9, title: "Kid A (Remastered)", artist: { id: 399, name: "Radiohead" }, cover_xl: "https://cdn/kida.jpg", nb_tracks: 10, link: "https://www.deezer.com/album/9" }] }));
    }
    if (String(url).startsWith("https://api.deezer.com/album/9")) return new Response(JSON.stringify({ id: 9, title: "Kid A (Remastered)", artist: { name: "Radiohead" }, duration: 2994, release_date: "2000-10-02",
      tracks: { data: [{ title: "Everything in Its Right Place", duration: 251 }, { title: "Kid A", duration: 284 }] } }));
    if (String(url).startsWith("https://itunes.apple.com/search")) {
      return new Response(JSON.stringify({ results: String(url).includes("Kid%20A") ? [
        { artistName: "Radiohead", collectionName: "Kid A - Single", collectionViewUrl: "https://music.apple.com/us/album/kid-a-single/2?uo=4" },
        { artistName: "Radiohead", collectionName: "Kid A", collectionViewUrl: "https://music.apple.com/us/album/kid-a/1?uo=4" }] : [] }));
    }
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

// The card's links line as [[text, url], …] (links are text, not buttons, since 2026-11-02; no «Ссылки:» word since
// 2026-11-08): the last line made of links only, not our site's 🌐 line
function cardLinks(c) {
  const line = (c.caption || c.text || "").split("\n").filter((l) => /^<a href=/.test(l)).at(-1) || "";
  return [...line.matchAll(/<a href="([^"]+)">([^<]+)<\/a>/g)].map((m) => [m[2], m[1].replace(/&amp;/g, "&")]);
}

test("follow from a card, hear about the next review once, with a link to the channel post", async () => {
  await newReviews([card("r1")]);                     // the card goes out; nobody follows yet
  await press(OWNER, "f:r1");
  assert.match(answers().at(-1).text, /Ты следишь за HMLTD/);
  assert.ok(calls.some((c) => c.method === "sendMessage" && c.chat_id === OWNER && /Мои артисты/.test(c.text)), "first follow explains the list");
  calls = [];
  assert.deepEqual(await newReviews([card("r2", "H", 124)]), { ok: true, sent: 1, pending: [] });
  const dm = calls.find((c) => c.method === "sendMessage");
  assert.equal(dm.chat_id, OWNER);
  assert.match(dm.text, /Новый обзор: <b>HMLTD — FANGS r2<\/b>, 🟡 5\/10/);
  assert.equal(dm.reply_markup.inline_keyboard[0][0].url, "https://t.me/chan/124");
  assert.equal(dm.disable_notification, undefined);
  assert.deepEqual(await newReviews([card("r2", "H", 124)]), { ok: true, sent: 0, pending: [] }, "a retry doesn't message twice");
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

test("with the site up, the card's last line is our site's page, named as ours (owner, 2026-11-02)", async () => {
  env.SITE_LIVE = "1";
  await say(OWNER, "kid a");
  const c = calls.find((x) => x.method === "sendPhoto");
  assert.match(c.caption, /^<b>Radiohead — Kid A<\/b>/); // the title itself is text: a link's text can't be copied
  // apart from the links by a blank line: it read as one of them (owner, 2026-11-02)
  assert.match(c.caption, /<\/blockquote>\n<a href=[^\n]+\n🌐 <a href="https:\/\/site\/r\/[^"]+\.html">На нашем сайте<\/a>$/);
});

test("one hit is sent as a full card: cover, length, links, marks and follow", async () => {
  await say(OWNER, "kid a");
  const c = calls.find((x) => x.method === "sendPhoto");
  assert.equal(c.photo, "https://cdn/kida.jpg");
  assert.match(c.caption, /<b>Radiohead — Kid A<\/b> \(2000\)\n🟢 10\/10 · art rock · 10 треков · 50 мин · 2-й из 2 обзоров артиста\n\n<b>Кто:<\/b> британская рок-группа, четвёртый альбом\n<b>Обзор:<\/b> Radiohead уходят в электронику\.\n/);
  assert.doesNotMatch(c.caption, /Not shown/); // the archive's brief (lmn/briefs.py) replaces Fantano's line
  // paragraphs: title and score, Fantano's words, the critics, when to listen (owner, 2026-11-01: one block read as glued)
  assert.match(c.caption, /электронику\.\n\n<b>Критики:<\/b> Metacritic 91 · Pitchfork 10\/10\nЧарты и продажи: US #1 · UK #1 \(<a href="https:\/\/en.wikipedia.org\/wiki\/Kid_A">Википедия<\/a>\)\n\n<b>Вайб для:<\/b>/);
  // the tracklist folded at the end, as in the channel's card
  // the tracklist folded, as in the channel's card, and the links under it (owner, 2026-11-02)
  // the quote stands out by itself: no blank lines around it (owner, 2026-11-02)
  assert.match(c.caption, /[^\n]\n<blockquote expandable><b>Треклист<\/b>\n1\. Everything in Its Right Place 4:11\n2\. Kid A 4:44<\/blockquote>\n<a href=[^\n]+$/);
  const btns = c.reply_markup.inline_keyboard.flat();
  // only actions are buttons; the links are the text's last line, under the tracklist (owner, 2026-11-02)
  assert.ok(btns.every((b) => !b.url));
  const links = cardLinks(c);
  // the archive has no video id for it, the site's per-review file has (from the video's page)
  assert.deepEqual(links[0], ["Видеообзор", "https://youtu.be/kidavideo01"]);
  assert.ok(!links.some(([t]) => t === "Все платформы" || /Google/.test(t))); // not in the bot (owner, 2026-11-02); the site keeps it
  assert.ok(links.some(([t, u]) => t === "Bandcamp" && u === "https://radiohead.bandcamp.com/album/kid-a")); // Fantano's "Listen:" link
  assert.ok(links.some(([t, u]) => t === "искать в YouTube Music" && u === "https://music.youtube.com/search?q=Radiohead%20Kid%20A"));
  // the exact album on Apple Music, not the single of the same name; SoundCloud only as a search
  assert.ok(links.some(([t, u]) => t === "Apple Music" && u === "https://music.apple.com/us/album/kid-a/1"));
  assert.ok(links.some(([t, u]) => t === "искать в SoundCloud" && u === "https://soundcloud.com/search?q=Radiohead%20Kid%20A"));
  assert.ok(!links.some(([t]) => t === "искать в Google")); // there is a Bandcamp page
  // the archive brief's mood guess: the channel card's vote, «другое» opens all four
  // «Вайб для» instead of «Когда слушать» (owner, 2026-11-02); the stored words stay
  // «для работы за столом» and «фоном» are one: «фоном для работы»
  assert.match(c.caption, /\n<b>Вайб для:<\/b> фона за работой <i>\(догадка ИИ, поправь кнопками\)<\/i>/);
  assert.ok(btns.some((b) => b.text === "для фона за работой: да" && b.callback_data === "w:k:14:y")); // MOODS index
  assert.ok(btns.some((b) => b.text === "Вайб: другое" && b.callback_data === "mq:k"));
  assert.ok(!btns.some((b) => b.text === "✨ Вайб для чего?"));
  await press(OWNER, "w:k:14:y");
  assert.deepEqual({ ...db.prepare("SELECT review_id, mood, vote FROM mood_votes").get() }, { review_id: "k", mood: "фоном для работы", vote: "y" });
  assert.ok(links.some(([t, u]) => t === "оценки на AOTY" && u === "https://www.albumoftheyear.org/search/?q=Radiohead%20Kid%20A"));
  assert.ok(btns.some((b) => b.callback_data === "m:k:done"));
  assert.ok(btns.some((b) => b.callback_data === "f:k"));
  assert.ok(btns.some((b) => b.text === "💿 Альбомы артиста" && b.callback_data === "da:k"));
  await press(OWNER, "f:k"); // an old review the bot never posted a card for
  assert.match(answers().at(-1).text, /Ты следишь за Radiohead/);
});

test("the album checked from Actions comes before Deezer's live search; a long tracklist links to all of it (owner, 2026-11-08)", async () => {
  rtAl = { cv: "https://caa/kida.jpg", y: "2000", min: 50, t: Array.from({ length: 60 }, (_, i) => [`Track number ${i + 1} with a long title`, 200]) };
  await say(OWNER, "kid a");
  assert.ok(!fetched.some((u) => u.startsWith("https://api.deezer.com/search/album"))); // no live search
  const c = calls.find((x) => x.method === "sendPhoto");
  assert.equal(c.photo, "https://caa/kida.jpg");
  // «Кто» and «Обзор» in one paragraph (owner, 2026-11-08)
  assert.match(c.caption, /\n\n<b>Кто:<\/b> британская рок-группа, четвёртый альбом\n<b>Обзор:<\/b> Radiohead уходят/);
  assert.match(c.caption, /\n<a href="https:\/\/t\.me\/bot\?start=t_k">… ещё \d+<\/a><\/blockquote>/);
  calls = [];
  await say(OWNER, "/start t_k"); // the link: the whole tracklist, nothing else
  const t = calls.find((x) => x.method === "sendMessage");
  assert.match(t.text, /^<b>Radiohead — Kid A<\/b>\n🟢 10\/10 · art rock · вышел 2000 · 50 мин · 60 треков\n\n1\. Track number 1 with a long title 3:20\n/);
  assert.match(t.text, /\n60\. Track number 60 with a long title 3:20$/);
  assert.ok(!t.reply_markup);
});

test("«💿 Альбомы артиста» from the channel opens the bot for someone who never started it", async () => {
  await tgUpdate({ callback_query: { id: "q", from: { id: 777 }, data: "da:k" } });
  assert.equal(answers().at(-1).url, "https://t.me/bot?start=da_k");
  calls = [];
  await say(777, "/start da_k");
  assert.ok(calls.some((x) => x.method === "sendMessage" && /^Radiohead — альбомы/.test(x.text || "")));
});

test("a card too long for a photo's caption is a message with the cover above and the whole tracklist", async () => {
  longBrief = "Очень длинное описание. ".repeat(45); // ~1100 characters
  await say(OWNER, "kid a");
  assert.ok(!calls.some((x) => x.method === "sendPhoto")); // not tried: it would fail
  const c = calls.find((x) => x.method === "sendMessage" && /Kid A/.test(x.text));
  assert.deepEqual(c.link_preview_options, { url: "https://cdn/kida.jpg", prefer_large_media: true, show_above_text: true });
  assert.match(c.text, /1\. Everything in Its Right Place 4:11\n2\. Kid A 4:44<\/blockquote>\n<a href=[^\n]+$/);
});

test("without a Deezer match the card is text, with the same links", async () => {
  await press(OWNER, "a:x");
  const c = calls.find((x) => x.method === "sendMessage" && /Obscure/.test(x.text));
  assert.match(c.text, /⚪ без оценки · обзор 2011/);
  assert.deepEqual(cardLinks(c).map(([t]) => t), ["Обзор", "искать в YouTube Music", "искать в SoundCloud", "оценки на AOTY"]);
});

test("an artist's albums without Fantano's review, and a card for one of them", async () => {
  await say(OWNER, "radiohead");
  const list = calls.find((c) => c.method === "sendMessage");
  assert.deepEqual(list.reply_markup.inline_keyboard.at(-2)[0], { text: "💿 Все альбомы артиста", callback_data: "da:k" });
  assert.deepEqual(list.reply_markup.inline_keyboard.at(-1)[0], { text: "🎬 Radiohead: от худшего к лучшему (2017)", url: "https://youtu.be/uu8sC7YDOZg" });
  calls = [];
  await press(OWNER, "da:k");
  const other = calls.find((c) => c.method === "sendMessage");
  assert.equal(other.text, "Radiohead — альбомы:");
  // the whole list, newest first by the first release's year (owner, 2026-11-03: the artist first, not Fantano): the
  // reviewed ones with their score open the review, the others their card; the undated one left out; the compilation
  // and the remixes wait behind their own button
  assert.deepEqual(other.reply_markup.inline_keyboard.map((r) => [r[0].text, r[0].callback_data || r[0].url]), [
    ["🟢 8/10 · A Moon Shaped Pool · обзор 2016", "a:p"],
    ["💿 Amnesiac · 2001", `mb:${AMNESIAC}`], // from the second page
    ["🟢 10/10 · Kid A · 2000", "a:k"], // MusicBrainz's year of the album, not the review's
    ["💿 The Bends · 1995", `mb:${BENDS}`],
    ["💿 My Iron Lung · 1994 · EP", `mb:${LUNG}`],
    ["💿 Pablo Honey · 1993", `mb:${PABLO}`],
    ["Ещё: концертные, сборники, ремиксы (2)", "dx:k"],
    ["🎬 Radiohead: от худшего к лучшему (2017)", "https://youtu.be/uu8sC7YDOZg"]]);
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
  assert.match(c.caption, new RegExp('^<b>Radiohead — The Bends</b> \\(1995\\)\n⚪ Фантано не обозревал · Alternative · 12 треков · 49 мин' +
    '\n\n<b>Критики:</b> Pitchfork 10/10 · AllMusic 5/5\nЧарты и продажи: US #88 · UK #4 · UK 4× Platinum \\(<a href="https://en.wikipedia.org/wiki/The_Bends">Википедия</a>\\)\n\n<a href='));
  const btns = c.reply_markup.inline_keyboard.flat();
  assert.deepEqual(cardLinks(c).map(([t]) => t), ["искать в YouTube Music", "искать в SoundCloud", "оценки на AOTY"]);
  assert.ok(btns.some((b) => b.callback_data === "f:k"));
  calls = [];
  mbDown = true; // MusicBrainz busy: the card is made from the list button's title and year
  await tgUpdate({ callback_query: { id: "q", from: { id: OWNER }, data: `mb:${BENDS}`, message: { message_id: 78, text: other.text, reply_markup: other.reply_markup } } });
  assert.match(calls.find((x) => x.method === "sendPhoto").caption, /^<b>Radiohead — The Bends<\/b> \(1995\)\n⚪ Фантано не обозревал · Alternative · 12 треков/);
  mbDown = false;
  calls = [];
  await press(OWNER, "dz:9"); // a reviewed album opened from Deezer gets the usual card
  assert.match(calls.find((x) => x.method === "sendPhoto").caption, /^<b>Radiohead — Kid A<\/b>/);
  calls = [];
  // «💿 Альбомы артиста» on a card of an album without a review: the artist's name comes from the saved card
  db.prepare("INSERT INTO unreviewed (id, artist_name, album) VALUES ('dz77', 'Radiohead', 'The Bends')").run();
  await press(OWNER, "ua:dz77");
  assert.match(calls.find((x) => x.method === "sendMessage").text, /^Radiohead — альбомы:/);
});

test("when MusicBrainz is down, the list comes from Deezer: albums only, the first edition's year", async () => {
  mbDown = true;
  await press(OWNER, "da:k");
  const other = calls.find((c) => c.method === "sendMessage");
  assert.equal(other.text, "Radiohead — альбомы:");
  // the later Bends edition and the single are left out; newest first; no extras button
  assert.deepEqual(other.reply_markup.inline_keyboard.map((r) => [r[0].text, r[0].callback_data || r[0].url]),
    [["💿 OK Computer OKNOTOK 1997 2017 · 2017", "dz:22"], ["🟢 8/10 · A Moon Shaped Pool · обзор 2016", "a:p"],
     ["🟢 10/10 · Kid A · 2000", "a:k"], ["💿 The Bends · 1995", "dz:20"],
     ["🎬 Radiohead: от худшего к лучшему (2017)", "https://youtu.be/uu8sC7YDOZg"]]);
  calls = [];
  await press(OWNER, "dz:20");
  assert.match(calls.find((x) => x.method === "sendPhoto").caption, /^<b>Radiohead — The Bends<\/b> \(1995\)/);
});

test("an album without a review gets AOTY's genres, critics, tracklist and album links from the owner's table (2026-11-08)", async () => {
  topU = { "radiohead--wallofeyes": { d: "2024-01-26", s: 83, g: ["art rock", "psychedelic rock"],
    c: [["Pitchfork", "8.2/10"], ["The Guardian", "4/5"], ["NME", "4/5"], ["Mojo", "4/5"]], tr: [["Wall of Eyes", 315], ["Teleharmonic", 344]],
    am: "https://music.apple.com/us/album/wall-of-eyes/1", bc: "https://thesmile.bandcamp.com/album/wall-of-eyes", sc: "https://soundcloud.com/thesmile/sets/wall-of-eyes" } };
  await press(OWNER, "dz:30");
  const c = calls.find((x) => x.method === "sendPhoto");
  assert.ok(fetched.includes("https://site/u/ra.json"));
  // AOTY's genres instead of Deezer's «Alternative»; Deezer's count and length stay; the table's year when Deezer gave none
  assert.match(c.caption, /^<b>Radiohead — Wall of Eyes<\/b> \(2026\)\n⚪ Фантано не обозревал · art rock, psychedelic rock · 8 треков · 45 мин/);
  assert.match(c.caption, /<b>Критики:<\/b> Pitchfork 8\.2\/10 · The Guardian 4\/5 · NME 4\/5 · AOTY 83\/100/);
  assert.match(c.caption, /<blockquote expandable><b>Треклист<\/b>\n1\. Wall of Eyes 5:15\n2\. Teleharmonic 5:44<\/blockquote>/);
  assert.deepEqual(cardLinks(c), [["искать в YouTube Music", "https://music.youtube.com/search?q=Radiohead%20Wall%20of%20Eyes"],
    ["Apple Music", "https://music.apple.com/us/album/wall-of-eyes/1"], ["SoundCloud", "https://soundcloud.com/thesmile/sets/wall-of-eyes"],
    ["Bandcamp", "https://thesmile.bandcamp.com/album/wall-of-eyes"], ["оценки на AOTY", "https://www.albumoftheyear.org/search/?q=Radiohead%20Wall%20of%20Eyes"]]);
  assert.ok(!fetched.some((u) => u.startsWith("https://itunes.apple.com/"))); // the table's Apple link: no live search
});

test("an album without a review can be put off: it shows in «⏳ Послушать потом»", async () => {
  await press(OWNER, `mb:${BENDS}`);
  const card = calls.find((x) => x.method === "sendPhoto");
  const btns = card.reply_markup.inline_keyboard;
  // two a row; «♡ Понравилось» is its own mark (owner, 2026-11-02)
  assert.deepEqual(btns.slice(0, 2).map((r) => r.map((b) => b.text)), [["✓ Слушал", "♡ Понравилось"], ["⏳ Послушать потом", "✗ Не моё"]]);
  assert.ok(!cardLinks(card).some(([t]) => /Google/.test(t))); // no Google search on cards (owner, 2026-11-08)
  assert.ok(btns.flat().every((b) => !b.url)); // only actions are buttons
  await press(OWNER, `m:${BENDS}:later`);
  calls = [];
  await say(OWNER, "📌 Отложенные"); // an old keyboard's button still works
  const list = calls.find((c) => c.method === "sendMessage");
  assert.match(list.text, /^Послушать потом: 1\./);
  assert.deepEqual(list.reply_markup.inline_keyboard, [[{ text: "⏳ Radiohead — The Bends", callback_data: `mb:${BENDS}` }]]);
});

test("a reviewed album: Fantano's line, favourites with a player on the site, n-th review, «Вайб для чего?», put off", async () => {
  await press(OWNER, "a:p");
  const c = calls.find((x) => x.method === "sendPhoto" || (x.method === "sendMessage" && /Moon/.test(x.text)));
  const text = c.caption || c.text;
  assert.match(text, /1-й из 2 обзоров артиста\n\n💬 <i>Radiohead return &amp; shine\.<\/i>\n★ Любимые у Фантано: DAYDREAMING, TRUE LOVE WAITS/);
  const btns = c.reply_markup.inline_keyboard.flat();
  assert.ok(btns.some((b) => b.text === "🔔 Следить") && btns.some((b) => b.text === "💿 Альбомы артиста" && b.callback_data === "da:p"));
  assert.ok(!cardLinks(c).some(([t]) => /любимые треки/.test(t))); // the player is on the site, not linked from the bot (owner, 2026-11-02)
  // the Apple link found from Actions (lmn/apple.py, in rt): Apple's search isn't asked (it often refuses the Worker)
  assert.ok(cardLinks(c).some(([t, u]) => t === "Apple Music" && u === "https://music.apple.com/us/album/a-moon-shaped-pool/5"));
  assert.ok(!fetched.some((u) => u.startsWith("https://itunes.apple.com/")));
  assert.ok(!btns.some((b) => /Отрывки/.test(b.text)));
  calls = [];
  await press(OWNER, "mq:p");  // art rock, no AI guess: the genre's four, then «Другие варианты»
  const m = calls.find((x) => x.method === "sendMessage");
  assert.equal(m.text, "Для чего вайб у <b>Radiohead — A Moon Shaped Pool</b>?");
  assert.deepEqual(m.reply_markup.inline_keyboard.map((row) => row.map((b) => b.text)),
    [["для вдумчивого слушания", "для злости"], ["для дороги", "для прогулки"], ["Другие варианты"]]); // «ночью» retired
  assert.equal(m.reply_markup.inline_keyboard[0][0].callback_data, "vo:p:10");
  calls = [];
  await press(OWNER, "ma:p");
  const all = calls.find((x) => x.method === "editMessageText");
  assert.equal(all.reply_markup.inline_keyboard.flat().length, 10); // the ten vibes left (owner, 2026-11-02)
  assert.ok(!all.reply_markup.inline_keyboard.flat().some((b) => /настроения|ночи|бодрости|за столом|^для фона$/.test(b.text)));
  assert.ok(all.reply_markup.inline_keyboard.flat().some((b) => b.text === "для фона за работой" && b.callback_data === "vo:p:14"));
  await press(OWNER, "vo:p:4");
  calls = [];
  await press(OWNER, "vo:p:6"); // an old message's «ночью»: retired, not stored
  assert.equal(calls.find((c) => c.method === "answerCallbackQuery").text, "Этого варианта больше нет");
  assert.ok(!db.prepare("SELECT 1 FROM mood_votes WHERE review_id='p' AND mood='ночью'").get());
  await press(OWNER, "vo:p:11"); // an old «фоном»: counts as «фоном для работы»
  assert.ok(db.prepare("SELECT 1 FROM mood_votes WHERE review_id='p' AND mood='фоном для работы'").get());
  calls = [];
  await press(OWNER, "mq:k");  // the archive brief's guess comes first, the genre's fill the rest
  assert.deepEqual(calls.find((x) => x.method === "sendMessage").reply_markup.inline_keyboard[0].map((b) => b.text),
    ["для фона за работой", "для вдумчивого слушания"]);
  assert.ok(db.prepare("SELECT 1 FROM mood_votes WHERE review_id='p' AND mood='в дорогу'").get());
  await press(OWNER, "m:k:later");
  calls = [];
  await say(OWNER, "⏳ Послушать потом");
  assert.deepEqual(calls.find((x) => x.method === "sendMessage").reply_markup.inline_keyboard, [[{ text: "⏳ Radiohead — Kid A", callback_data: "a:k" }]]);
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

test("many followers are told in portions, each once, and the review stays pending until all have it", async () => {
  await newReviews([card("r1")]);
  for (let uid = 100; uid < 160; uid++) {
    db.prepare("INSERT INTO users (user_id, started_at) VALUES (?, ?)").run(uid, "2026-10-31");
    db.prepare("INSERT INTO follows (user_id, name_key, artist_name, mbid, created_at) VALUES (?, 'hmltd', 'HMLTD', 'H', '2026-11-01')").run(uid);
  }
  calls = [];
  const first = await newReviews([card("r2", "H", 124)]);
  assert.ok(first.sent > 20 && first.sent < 60, `a portion: ${first.sent}`);
  assert.deepEqual(first.pending, ["r2"]);
  const second = await newReviews([card("r2", "H", 124)]);
  assert.equal(first.sent + second.sent, 60);
  assert.deepEqual(second.pending, []);
  const told = calls.filter((c) => c.method === "sendMessage").map((c) => c.chat_id);
  assert.equal(new Set(told).size, told.length, "nobody is told twice");
});

test("reminders for many people go out over several days, one per person", async () => {
  for (let uid = 100; uid < 160; uid++) {
    db.prepare("INSERT INTO users (user_id, started_at) VALUES (?, ?)").run(uid, "2026-10-31");
    db.prepare("INSERT INTO marks (user_id, review_id, status, later_at, updated_at) VALUES (?, 'k', 'later', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')").run(uid);
    db.prepare("INSERT INTO marks (user_id, review_id, status, later_at, updated_at) VALUES (?, 'p', 'later', '2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z')").run(uid);
  }
  const day = async () => {
    calls = [];
    const ps = [];
    await worker.scheduled({ cron: "0 9 * * *", scheduledTime: Date.UTC(2026, 10, 3, 9) }, env, { waitUntil: (p) => ps.push(p) });
    await Promise.all(ps);
    return calls.filter((c) => c.method === "sendMessage" && /Три недели назад/.test(c.text));
  };
  const d1 = await day();
  assert.ok(d1.length > 20 && d1.length < 60, `a portion: ${d1.length}`);
  assert.ok(d1.every((m) => /Kid A/.test(m.text)), "the first put off");
  const d2 = await day();
  const d3 = await day();
  const all = [...d1, ...d2, ...d3].map((m) => m.chat_id);
  assert.equal(all.length, 60);
  assert.equal(new Set(all).size, 60, "one reminder per person");
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
  await press(OWNER, "m:k:done"); // Kid A as listened: a list of similar albums follows
  const first = calls.findIndex((c) => c.method === "answerCallbackQuery");
  const firstCard = calls.findIndex((c) => c.method === "sendMessage" && /^Похожие|^Пока не можем/.test(c.text || ""));
  assert.ok(first >= 0 && firstCard > first, `answer at ${first}, first similar message at ${firstCard}`);
  assert.equal(answers().length, 1, "answered exactly once");
  calls = [];
  await press(OWNER, "a:k");
  assert.equal(calls[0].method, "answerCallbackQuery");
  assert.equal(answers().length, 1);
});

test("no pinned list in a private chat: an old one goes at the next mark, «⏳ Послушать потом» shows the list (owner, 2026-11-02)", async () => {
  db.prepare("INSERT INTO users (user_id, started_at, dm_pinned_id) VALUES (?, ?, ?)").run(OTHER, "2026-11-01", 900);
  await press(OTHER, "m:k:later");
  assert.ok(calls.some((c) => c.method === "unpinChatMessage" && c.chat_id === OTHER && c.message_id === 900));
  assert.ok(calls.some((c) => c.method === "deleteMessage" && c.chat_id === OTHER && c.message_id === 900));
  assert.equal(db.prepare("SELECT dm_pinned_id FROM users WHERE user_id=?").get(OTHER).dm_pinned_id, null);
  calls = [];
  await press(OTHER, `mb:${BENDS}`);
  await press(OTHER, `m:${BENDS}:later`);
  assert.ok(!calls.some((c) => ["pinChatMessage", "editMessageText", "unpinChatMessage"].includes(c.method) && c.chat_id === OTHER));
  calls = [];
  await say(OTHER, "⏳ Послушать потом");
  const list = calls.find((c) => c.method === "sendMessage" && c.chat_id === OTHER && /^Послушать потом:/.test(c.text));
  assert.match(list.text, /^Послушать потом: 2\./);
  assert.equal(list.reply_markup.inline_keyboard[0][0].text, "⏳ Radiohead — Kid A"); // the first put off first, as in «Наверстать»
});

test("/start pins nothing in the private chat", async () => {
  await say(OTHER, "/start");
  assert.ok(!calls.some((c) => c.method === "pinChatMessage"));
});

test("a link from a pinned list: the card in the private chat, the «/start» it sent removed", async () => {
  calls = [];
  await tgUpdate({ message: { chat: { type: "private" }, from: { id: OWNER }, message_id: 41, text: "/start a_k" } });
  assert.deepEqual(calls.filter((c) => c.method === "deleteMessage").map((c) => [c.chat_id, c.message_id]), [[OWNER, 41]]);
  const shown = calls.find((c) => c.method === "sendPhoto" || (c.method === "sendMessage" && c.text.includes("Kid A")));
  assert.ok((shown.caption || shown.text).includes("Radiohead — Kid A"));
  assert.equal(shown.chat_id, OWNER);
  // someone new (tapped in the channel): greeted, then the card; nothing to delete
  calls = [];
  await tgUpdate({ message: { chat: { type: "private" }, from: { id: 3 }, message_id: 7, text: `/start mb_${BENDS}` } });
  assert.equal(calls.filter((c) => c.method === "deleteMessage").length, 0);
  assert.match(calls[0].text, /^Привет!/);
  assert.ok(calls.some((c) => c.method === "sendPhoto" && c.chat_id === 3 && c.caption.includes("The Bends")));
});

test("start parameters: only a card's own kinds and safe characters", async () => {
  const { openFromStart, startLink } = await import("../src/links.mjs");
  assert.equal(openFromStart("/start a_6ae16e7060a520b7b082e3e1"), "a:6ae16e7060a520b7b082e3e1");
  assert.equal(openFromStart("/start dz_302127"), "dz:302127");
  assert.equal(openFromStart("/start follow_k"), null);
  assert.equal(openFromStart("/start a_x y"), null);
  assert.equal(openFromStart("/start"), null);
  assert.equal(startLink({ BOT_USERNAME: "b" }, "a:YGFqOLufncA"), "https://t.me/b?start=a_YGFqOLufncA");
});

// ---------- «Наверстать» (was «Дослушать») ----------

test("«Наверстать» without marks asks after which album, then lists the newer reviews oldest first", async () => {
  await say(OWNER, "▶ Наверстать");
  assert.match(calls.at(-1).text, /^Отметок «Слушал» у тебя пока нет\. После какого альбома начать\?/);
  calls = [];
  await say(OWNER, "obscure nothing"); // the answer, not a search
  const list = calls.find((c) => c.method === "sendMessage");
  assert.match(list.text, /^<b>Наверстать<\/b> после Obscure — Nothing \(01\.01\.2011\)\n2 обзора, здесь 1–2\n\n/);
  assert.ok(list.text.indexOf("start=q_p") < list.text.indexOf("start=q_k"), "the older one first");
  assert.deepEqual(list.reply_markup.inline_keyboard[0], [{ text: "▶ С первого", callback_data: "qo:p" }]);
  calls = [];
  await say(OWNER, "kid a"); // the question was answered: a search again
  assert.ok(calls.some((c) => c.method === "sendPhoto"));
});

test("«после какого альбома?» is answered once: no match or a late answer is an ordinary search", async () => {
  await say(OWNER, "▶ Дослушать"); // an old keyboard's button still works
  calls = [];
  await say(OWNER, "zzzz nothing like it");
  assert.match(calls.find((c) => c.method === "sendMessage").text, /^Среди обзоров такого не нашёл/);
  calls = [];
  await say(OWNER, "kid a"); // not taken as the answer any more
  assert.ok(calls.some((c) => c.method === "sendPhoto"));
  assert.ok(!calls.some((c) => /Наверстать<\/b>/.test(c.text || "")));

  await say(OWNER, "▶ Наверстать");
  db.prepare("UPDATE settings SET value=? WHERE key=?").run(new Date(Date.now() - 11 * 60e3).toISOString(), `qfrom:${OWNER}`);
  calls = [];
  await say(OWNER, "obscure nothing"); // eleven minutes later: a search
  assert.ok(!calls.some((c) => /Наверстать<\/b>/.test(c.text || "")));
  assert.equal(db.prepare("SELECT count(*) AS n FROM settings WHERE key=?").get(`qfrom:${OWNER}`).n, 0);
});

test("the start is the latest review heard, not the last marked; an old one is confirmed first", async () => {
  await press(OWNER, "m:p:done");
  await press(OWNER, "m:x:nope"); // marked later, but its review is older
  calls = [];
  await say(OWNER, "/listen");
  const ask = calls.find((c) => c.method === "sendMessage");
  assert.match(ask.text, /^Последний прослушанный у тебя — <b>Radiohead — A Moon Shaped Pool<\/b>, обзор от 10\.05\.2016\. После него 1 обзор: это больше года\./);
  assert.deepEqual(ask.reply_markup.inline_keyboard[0], [{ text: "Да, показать", callback_data: "ql:p:0" }]);
  calls = [];
  await press(OWNER, "ql:p:0", 555);
  const list = calls.find((c) => c.method === "editMessageText" && c.message_id === 555);
  assert.match(list.text, /🟢 10\/10 · <a href="https:\/\/t\.me\/bot\?start=q_k">Radiohead — Kid A<\/a> · art rock · 01\.01\.2020/);
  // confirmed: the place is remembered, so it isn't asked again
  calls = [];
  await say(OWNER, "/listen");
  assert.match(calls.find((c) => c.method === "sendMessage").text, /^<b>Наверстать<\/b> после Radiohead — A Moon Shaped Pool/);
});

test("an old start not yet confirmed is asked about again, not remembered by showing the question", async () => {
  await press(OWNER, "m:p:done");
  await say(OWNER, "/listen");
  calls = [];
  await say(OWNER, "/listen");
  assert.match(calls.find((c) => c.method === "sendMessage").text, /^Последний прослушанный у тебя — /);
});

test("a card from the list: «✓ Послушал → дальше» marks it, removes it and sends the next; the end gets the trophy", async () => {
  await say(OWNER, "/start q_x");
  const first = calls.find((c) => c.method === "sendMessage" || c.method === "sendPhoto");
  const kb = first.reply_markup.inline_keyboard;
  // no «✓ Слушал» next to «Послушал → дальше»; every mark moves on, so none overwrites another (owner, 2026-11-02)
  assert.deepEqual(kb[0], [{ text: "♡ Понравилось", callback_data: "lk:x" }, { text: "✓ Послушал → дальше", callback_data: "qd:x" }]);
  assert.deepEqual(kb[1], [{ text: "⏳ Потом → дальше", callback_data: "qd:x:later" }, { text: "✗ Не моё → дальше", callback_data: "qd:x:nope" }]);
  assert.deepEqual(kb[2], [{ text: "← Назад", callback_data: "qb:x" }, { text: "Пропустить →", callback_data: "qs:x" }]);
  assert.match(first.caption || first.text, /^▶ <i>Навёрстываю · после этого ещё 2 обзора<\/i>/);
  calls = [];
  await press(OWNER, "qd:x", 901);
  assert.equal(db.prepare("SELECT status FROM marks WHERE user_id=? AND review_id='x'").get(OWNER).status, "done");
  assert.ok(calls.some((c) => c.method === "deleteMessage" && c.message_id === 901));
  const next = calls.find((c) => c.method === "sendPhoto" || (c.method === "sendMessage" && /Moon/.test(c.text)));
  assert.match(next.caption || next.text, /Radiohead — A Moon Shaped Pool/);
  calls = [];
  await press(OWNER, "qb:p", 905); // back: this card goes, the review before it comes again
  assert.ok(calls.some((c) => c.method === "deleteMessage" && c.message_id === 905));
  const back = calls.find((c) => c.method === "sendPhoto" || c.method === "sendMessage");
  assert.equal(back.reply_markup.inline_keyboard[0][1].callback_data, "qd:x");
  calls = [];
  await press(OWNER, "qs:p", 902); // skipped: not marked
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM marks WHERE user_id=? AND review_id='p'").get(OWNER).n, 0);
  calls = [];
  await press(OWNER, "qd:p:later", 904); // put off: in «Послушать потом», this card goes, the next comes
  assert.equal(db.prepare("SELECT status FROM marks WHERE user_id=? AND review_id='p'").get(OWNER).status, "later");
  assert.ok(calls.some((c) => c.method === "deleteMessage" && c.message_id === 904));
  assert.ok(calls.some((c) => (c.method === "sendPhoto" || c.method === "sendMessage") && /Навёрстываю/.test(c.caption || c.text || "")));
  calls = [];
  await say(OWNER, "⏳ Послушать потом");
  assert.match(calls.find((c) => c.method === "sendMessage").text, /^Послушать потом: 1/);
  calls = [];
  await press(OWNER, "qd:k", 903);
  assert.match(calls.find((c) => c.method === "sendMessage" && /🤘<\/tg-emoji> <b>Ты нагнал/.test(c.text)).text, /Ты нагнал\(а\) всё до самого нового обзора Фантано!.*\nУ тебя 2 обзора с отметкой «прослушано»/s);
});

test("«♡ Понравилось» is its own mark: «Слушал» keeps it, «Не моё» drops it, «♥ Понравившееся» lists it (owner, 2026-11-02)", async () => {
  const card = { message_id: 70, chat: { id: OWNER, type: "private" }, reply_markup: { inline_keyboard: [[{ text: "✓ Слушал", callback_data: "m:k:done" }, { text: "♡ Понравилось", callback_data: "lk:k" }]] } };
  const tap = (data) => tgUpdate({ callback_query: { id: "q", from: { id: OWNER }, data, message: card } });
  await tap("lk:k");
  assert.ok(db.prepare("SELECT 1 FROM likes WHERE user_id=? AND review_id='k'").get(OWNER));
  assert.equal(calls.find((c) => c.method === "answerCallbackQuery").text, "♥ В списке «Понравившееся»");
  const edit = calls.find((c) => c.method === "editMessageReplyMarkup");
  assert.deepEqual(edit.reply_markup.inline_keyboard[0][1], { text: "♥ Понравилось", callback_data: "lk:k" }); // the heart shows it
  await tap("m:k:done");
  assert.ok(db.prepare("SELECT 1 FROM likes WHERE user_id=? AND review_id='k'").get(OWNER), "«Слушал» doesn't drop the like");
  await press(OWNER, "qd:p:later");
  await press(OWNER, "lk:p"); // a channel post or a card without a keyboard: no edit, the answer says it
  calls = [];
  await say(OWNER, "♥ Понравившееся");
  const list = calls.find((c) => c.method === "sendMessage");
  // as in «Наверстать»: colour and score · Artist — Album (its card) · genre · review date; the last liked first
  assert.equal(list.text, "<b>♥ Понравившееся</b> · 2\n\n" +
    '🟢 8/10 · <a href="https://t.me/bot?start=a_p">Radiohead — A Moon Shaped Pool</a> · art rock · 10.05.2016\n' +
    '🟢 10/10 · <a href="https://t.me/bot?start=a_k">Radiohead — Kid A</a> · art rock · 01.01.2020\n\nНажми на альбом: пришлю его карточку.');
  calls = [];
  await press(OWNER, "m:k:nope"); // not mine and liked don't go together
  assert.ok(!db.prepare("SELECT 1 FROM likes WHERE user_id=? AND review_id='k'").get(OWNER));
  assert.equal(calls.find((c) => c.method === "answerCallbackQuery").text, "Отмечено: ✗ не понравилось, и убрано из понравившегося");
  await press(OWNER, "lk:k"); // liking it again takes back «не моё»
  assert.equal(db.prepare("SELECT status FROM marks WHERE user_id=? AND review_id='k'").get(OWNER).status, "done");
  await press(OWNER, "lk:k"); // and off
  assert.ok(!db.prepare("SELECT 1 FROM likes WHERE user_id=? AND review_id='k'").get(OWNER));
  calls = [];
  await say(OWNER, "/liked");
  assert.match(calls.find((c) => c.method === "sendMessage").text, /· 1\n/);
});

test("«Наверстать» lists «Послушать потом» first, goes through it, then on from the place it remembers", async () => {
  await press(OWNER, "m:x:done"); // the place: after Obscure (2011)
  await press(OWNER, "m:k:later"); // the newest review, put off
  calls = [];
  await say(OWNER, "▶ Наверстать");
  const list = calls.find((c) => c.method === "sendMessage");
  assert.match(list.text, /^<b>Наверстать<\/b>\n\n<b>⏳ Послушать потом<\/b> · 1\n\n.*start=q_k.*\n\n<b>Новые обзоры<\/b> после Obscure — Nothing \(01\.01\.2011\)\n2 обзора, здесь 1–2\n\n.*start=q_p.*\n.*start=q_k.* ⏳\n\n.*сначала из «Послушать потом»\.$/s);
  assert.deepEqual(list.reply_markup.inline_keyboard[0], [{ text: "▶ С первого", callback_data: "qo:k" }]);
  calls = [];
  await press(OWNER, "qo:k");
  const card = calls.find((c) => c.method === "sendPhoto" || c.method === "sendMessage");
  assert.match(card.caption || card.text, /^▶ <i>Навёрстываю · послушать потом, это последний, потом новые обзоры<\/i>/);
  assert.deepEqual(card.reply_markup.inline_keyboard.slice(0, 3), [
    [{ text: "♡ Понравилось", callback_data: "lk:k" }, { text: "✓ Послушал → дальше", callback_data: "qd:k:done:l" }],
    [{ text: "✗ Не моё → дальше", callback_data: "qd:k:nope:l" }, { text: "Пропустить →", callback_data: "qs:k:l" }],
    [{ text: "← Назад", callback_data: "qb:k:l" }]]);
  calls = [];
  await press(OWNER, "qb:k:l");
  assert.equal(calls.find((c) => c.method === "sendMessage").text, "Это первый альбом в «Послушать потом».");
  calls = [];
  // heard the newest review: the place stays after Obscure, so A Moon Shaped Pool (2016) comes next, not the trophy
  await press(OWNER, "qd:k:done:l", 910);
  assert.equal(db.prepare("SELECT status FROM marks WHERE user_id=? AND review_id='k'").get(OWNER).status, "done");
  const next = calls.find((c) => c.method === "sendPhoto" || (c.method === "sendMessage" && /Moon/.test(c.text)));
  assert.match(next.caption || next.text, /^▶ <i>Навёрстываю · после этого ещё 1 обзор<\/i>.*A Moon Shaped Pool/s);
  assert.equal(next.reply_markup.inline_keyboard[0][1].callback_data, "qd:p");
  calls = [];
  await say(OWNER, "/listen"); // the list too goes on from the place, not from Kid A
  assert.match(calls.find((c) => c.method === "sendMessage").text, /^<b>Наверстать<\/b> после Obscure — Nothing/);
  await press(OWNER, "qs:p"); // skipped in the reviews' part: the place moves to it
  calls = [];
  await say(OWNER, "/listen");
  assert.match(calls.find((c) => c.method === "sendMessage").text, /^<b>Наверстать<\/b> после Radiohead — A Moon Shaped Pool/);
});

test("the «Послушать потом» block: the first put off first, the last put off last (owner, 2026-11-02)", async () => {
  await press(OWNER, "m:x:done");
  await press(OWNER, "m:k:later");
  await press(OWNER, "m:p:later");
  db.prepare("UPDATE marks SET later_at=? WHERE review_id='k'").run("2026-11-01T10:00:00Z");
  db.prepare("UPDATE marks SET later_at=? WHERE review_id='p'").run("2026-11-02T10:00:00Z");
  calls = [];
  await say(OWNER, "▶ Наверстать");
  const list = calls.find((c) => c.method === "sendMessage");
  const block = list.text.split("<b>Новые обзоры</b>")[0];
  assert.ok(block.indexOf("start=q_k") < block.indexOf("start=q_p"), "Kid A, put off first, first");
  calls = [];
  await press(OWNER, "qo:k");
  assert.match(calls.find((c) => c.method === "sendPhoto" || c.method === "sendMessage").caption, /^▶ <i>Навёрстываю · послушать потом, после этого ещё 1<\/i>/);
  calls = [];
  await press(OWNER, "qd:k:done:l", 920); // Kid A leaves the block; the next is the block's next, not a newer review
  const next = calls.find((c) => c.method === "sendPhoto" || (c.method === "sendMessage" && /Moon/.test(c.text)));
  assert.match(next.caption || next.text, /^▶ <i>Навёрстываю · послушать потом, это последний, потом новые обзоры<\/i>.*A Moon Shaped Pool/s);
  calls = [];
  await press(OWNER, "qb:p:l"); // Kid A was heard: nothing before it in the block now
  assert.equal(calls.find((c) => c.method === "sendMessage").text, "Это первый альбом в «Послушать потом».");
  calls = [];
  await press(OWNER, "qb:k:l"); // a card that has left the block goes back to the block's last
  const last = calls.find((c) => c.method === "sendPhoto" || (c.method === "sendMessage" && /Moon/.test(c.text)));
  assert.match(last.caption || last.text, /^▶ <i>Навёрстываю · послушать потом.*A Moon Shaped Pool/s);
  calls = [];
  await press(OWNER, "qs:p:l"); // skipped: stays put off; the block is done and both reviews after Obscure are marked
  assert.equal(db.prepare("SELECT status FROM marks WHERE user_id=? AND review_id='p'").get(OWNER).status, "later");
  assert.ok(calls.some((c) => c.method === "sendMessage" && /🤘<\/tg-emoji> <b>Ты нагнал/.test(c.text)));
});

test("a vote button sent before «Вайб для» means the word it meant then; a retired word isn't stored", async () => {
  rtMoods = ["ночью", "в дорогу"]; // an old guess: the old buttons were v:k:0 «ночью», v:k:1 «в дорогу»
  await press(OWNER, "v:k:1:y");
  assert.deepEqual(db.prepare("SELECT mood, vote FROM mood_votes WHERE review_id='k'").all().map((x) => ({ ...x })), [{ mood: "в дорогу", vote: "y" }]);
  calls = [];
  await press(OWNER, "v:k:0:y");
  assert.equal(calls.find((c) => c.method === "answerCallbackQuery").text, "Этого варианта больше нет");
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM mood_votes WHERE review_id='k'").get().n, 1);
  rtMoods = ["фоном", "перед сном"];
  await press(OWNER, "v:k:0:n"); // merged since: counts as «фоном для работы»
  assert.equal(db.prepare("SELECT vote FROM mood_votes WHERE review_id='k' AND mood='фоном для работы'").get().vote, "n");
  await press(OWNER, "w:k:6:y"); // a w: button for a retired word can't be made, but isn't stored either
  assert.ok(!db.prepare("SELECT 1 FROM mood_votes WHERE mood='ночью'").get());
});

test("the new menu reaches an old keyboard once; «Как пользоваться» repeats the help", async () => {
  db.prepare("DELETE FROM settings WHERE key=?").run(`menu:${OWNER}`);
  await say(OWNER, "🎲 Случайный из архива");
  const note = calls.find((c) => c.method === "sendMessage" && /В меню обновление/.test(c.text));
  assert.deepEqual(note.reply_markup.keyboard, [[{ text: "▶ Наверстать" }, { text: "🎲 Случайный из архива" }],
    [{ text: "⏳ Послушать потом" }, { text: "♥ Понравившееся" }], [{ text: "🔔 Мои артисты" }, { text: "❓ Как пользоваться" }]]);
  calls = [];
  await say(OWNER, "❓ Как пользоваться");
  assert.equal(calls.filter((c) => /В меню обновление/.test(c.text || "")).length, 0);
  const help = calls.at(-1).text;
  assert.match(help, /<b>Наверстать\.<\/b>/);
  assert.doesNotMatch(help, /Лучшее|фан-проект|[✓✗]/); // the digest is off; no check marks in the text (owner, 2026-11-02)
});

test("a new album of a followed artist comes before Fantano's review, once; the first check only remembers", async () => {
  const at = (hours) => { const t = new Date(); t.setUTCHours(12, 0, 0, 0); return t.getTime() + hours * 3600e3; };
  const today = new Date(at(0)).toISOString().slice(0, 10);
  const tick = async (hours) => { const ps = []; await worker.scheduled({ cron: "30 * * * *", scheduledTime: at(hours) }, env, { waitUntil: (p) => ps.push(p) }); await Promise.all(ps); };
  await press(OWNER, "f:k"); // follows Radiohead
  freshAlbums = [{ id: 31, title: "Announced", release_date: "2099-01-01", record_type: "album" }];
  calls = [];
  await tick(0);
  // the Deezer artist found through the reviewed Kid A; what is out already is only remembered
  assert.deepEqual({ ...db.prepare("SELECT dz_id FROM watched_artists").get() }, { dz_id: 399 });
  assert.ok(!calls.some((c) => c.method === "sendPhoto" || c.method === "sendMessage"));
  await tick(1); // checked an hour ago: not again
  assert.equal(db.prepare("SELECT COUNT(*) n FROM new_releases").get().n, 0);
  freshAlbums = [
    { id: 30, title: "Wall of Eyes", release_date: today, record_type: "album" },
    { id: 32, title: "Wall of Eyes (Deluxe Edition)", release_date: today, record_type: "album" },
    { id: 33, title: "Read the Room", release_date: today, record_type: "single" },
    { id: 34, title: "The Bends (Live)", release_date: today, record_type: "album" },
    { id: 31, title: "Announced", release_date: "2099-01-01", record_type: "album" }];
  calls = [];
  await tick(21);
  const card = calls.filter((c) => c.method === "sendPhoto");
  assert.equal(card.length, 1); // the album only: no deluxe, single, or a live version of an old title
  assert.equal(card[0].chat_id, OWNER);
  assert.equal(card[0].photo, "https://cdn/woe.jpg");
  assert.match(card[0].caption, /^🔔 Новый альбом артиста, за которым ты следишь\n\n<b>Radiohead — Wall of Eyes<\/b>\n🆕 Вышел \d+ [а-я]+, обзоров пока нет · Alternative · 8 треков · 45 мин/);
  assert.ok(!cardLinks(card[0]).some(([t]) => /Apple/.test(t))); // not found there: no link (a search link is lost on a Mac)
  assert.ok(card[0].reply_markup.inline_keyboard.flat().some((b) => b.callback_data === "m:dz30:later"));
  calls = [];
  await tick(22);
  await tick(43);
  assert.ok(!calls.some((c) => c.method === "sendPhoto")); // once
});

test("new albums wait out the quiet hours", async () => {
  await press(OWNER, "f:k");
  const night = (() => { const t = new Date(); t.setUTCHours(23, 0, 0, 0); return t; })();
  const tick = async (t) => { const ps = []; await worker.scheduled({ cron: "30 * * * *", scheduledTime: t.getTime() }, env, { waitUntil: (p) => ps.push(p) }); await Promise.all(ps); };
  await tick(new Date(night.getTime() - 24 * 3600e3));
  freshAlbums = [{ id: 30, title: "Wall of Eyes", release_date: night.toISOString().slice(0, 10), record_type: "album" }];
  calls = [];
  await tick(night);
  assert.equal(db.prepare("SELECT COUNT(*) n FROM new_releases").get().n, 1);
  assert.ok(!calls.some((c) => c.method === "sendPhoto"));
  await tick(new Date(night.getTime() + 8 * 3600e3)); // 07:00 UTC, 10:00 in Moscow
  assert.equal(calls.filter((c) => c.method === "sendPhoto").length, 1);
});

test("after «✓ Слушал»: one message with similar albums as buttons, or a word that there are none", async () => {
  await say(OWNER, "/start");
  calls = [];
  await press(OWNER, "m:k:done");
  const sent = calls.filter((c) => c.method === "sendMessage" && /Похожие|Пока не можем/.test(c.text || ""));
  assert.equal(sent.length, 1);
  assert.ok(!calls.some((c) => c.method === "sendPhoto")); // no cards until one is pressed
  assert.match(sent[0].text, /^Похожие на <b>Radiohead — Kid A<\/b> по жанрам/);
  const btns = sent[0].reply_markup.inline_keyboard.flat();
  assert.ok(btns.some((b) => b.callback_data === "a:p")); // A Moon Shaped Pool: art rock, 8
  assert.ok(btns.length <= 6 && btns.every((b) => b.callback_data.startsWith("a:") && b.callback_data !== "a:k"));
  calls = [];
  await press(OWNER, `m:${BENDS}:done`); // an album without a review: nothing to compare its genres with
  assert.ok(calls.some((c) => c.method === "sendMessage" && /^Пока не можем найти похожие/.test(c.text)));
});
