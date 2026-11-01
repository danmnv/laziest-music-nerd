// Laziest Music Nerd — Cloudflare Worker.
// Handles Telegram button presses and /start, site login (Telegram Login Widget), personal marks,
// following artists, and a daily cron for "later" reminders. Personal marks are visible only to their owner.

import { isDigestSunday } from "./digest.mjs";
import { nameKey, followMatches } from "./follow.mjs";
import { answerSearch, artistReviews, badge } from "./search.mjs";
import { criticsText } from "./critics.mjs";
import { wikiCritics } from "./wiki.mjs";

const STATUS_LABEL = { later: "• отложено", done: "✓ прослушано", nope: "✗ не понравилось" };
const STATUS_ICON = { later: " •", done: " ✓", nope: " ✗" };
const LIST_HEAD = "<b>Свежие обзоры Фантано за 60 дней</b>\n\n";
const MESSAGE_LIMIT = 4096;
const MOODS = ["для тренировки", "для настроения", "для работы за столом", "для тусовки"];
const RANDOM_BUTTON = "🎲 Случайный из архива";
const FOLLOWS_BUTTON = "🔔 Мои артисты";
const LATER_BUTTON = "📌 Отложенные";
const MENU = { keyboard: [[{ text: RANDOM_BUTTON }], [{ text: FOLLOWS_BUTTON }, { text: LATER_BUTTON }]], resize_keyboard: true, is_persistent: true };
// Short enough for three (marks) or two (follow) buttons in a row on a phone without "…"
const MARK_ROW = (id) => [{ text: "• Отложить", callback_data: `m:${id}:later` }, { text: "✓ Слушал", callback_data: `m:${id}:done` },
  { text: "✗ Не моё", callback_data: `m:${id}:nope` }];

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    try {
      if (req.method === "OPTIONS") return cors(env, new Response(null, { status: 204 }));
      if (url.pathname === "/tg" && req.method === "POST") {
        if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
        ctx.waitUntil(onUpdate(await req.json(), env).catch((e) => console.log("update failed", e.stack)));
        return new Response("ok");
      }
      if (url.pathname === "/auth/telegram" && req.method === "POST") return cors(env, await login(await req.json(), env));
      if (url.pathname === "/api/public") return cors(env, json(await publicStats(env)));
      if (url.pathname === "/api/me/marks") {
        const uid = await sessionUser(req, env);
        if (!uid) return cors(env, json({ error: "login" }, 401));
        return cors(env, json({ marks: await userMarks(env, uid) }));
      }
      if (url.pathname === "/api/mark" && req.method === "POST") {
        const uid = await sessionUser(req, env);
        if (!uid) return cors(env, json({ error: "login" }, 401));
        const b = await req.json();
        await setMark(env, uid, String(b.review_id), b.status ?? undefined, b.score ?? undefined);
        if (isOwner(env, uid)) ctx.waitUntil(refreshOwnerLists(env));
        return cors(env, json({ ok: true }));
      }
      if (url.pathname === "/api/refresh-lists" && req.method === "POST") {
        // Called by GitHub Actions after a new review: refresh every pinned list in private chats.
        if (req.headers.get("Authorization") !== `Bearer ${env.ACTIONS_SECRET}`) return new Response("forbidden", { status: 403 });
        const body = await req.json().catch(() => ({}));
        if (Array.isArray(body.items)) await setSetting(env, "list_items", JSON.stringify(body.items));
        const { results } = await env.DB.prepare("SELECT user_id FROM users WHERE dm_pinned_id IS NOT NULL").all();
        ctx.waitUntil((async () => { for (const u of results) await refreshDmList(env, u.user_id, false); })());
        return json({ ok: true, users: results.length });
      }
      if (url.pathname === "/api/new-reviews" && req.method === "POST") {
        // Called by GitHub Actions right after cards are posted: remember each card's artist, message the followers.
        if (req.headers.get("Authorization") !== `Bearer ${env.ACTIONS_SECRET}`) return new Response("forbidden", { status: 403 });
        const body = await req.json().catch(() => ({}));
        let sent = 0;
        for (const r of Array.isArray(body.reviews) ? body.reviews : []) sent += await tellFollowers(env, r);
        return json({ ok: true, sent });
      }
      if (url.pathname === "/api/owner/id") {
        // For GitHub Actions' test mode and key check: once the webhook is set, Telegram's getUpdates is closed to them.
        if (req.headers.get("Authorization") !== `Bearer ${env.ACTIONS_SECRET}`) return new Response("forbidden", { status: 403 });
        return json({ owner_id: env.OWNER_ID ? Number(env.OWNER_ID) : null });
      }
      if (url.pathname === "/api/owner/channel-marks") {
        if (req.headers.get("Authorization") !== `Bearer ${env.ACTIONS_SECRET}`) return new Response("forbidden", { status: 403 });
        const show = (await getSetting(env, "show_in_channel")) !== "0";
        return json({ marks: show && env.OWNER_ID ? statusMap(await userMarks(env, Number(env.OWNER_ID))) : {} });
      }
      return new Response("Laziest Music Nerd", { status: 200 });
    } catch (e) {
      console.log("error", e.stack);
      return cors(env, json({ error: "server" }, 500));
    }
  },

  async scheduled(event, env, ctx) {
    if (event.cron === "0 7 * * SUN") ctx.waitUntil(sendDigest(env));
    else ctx.waitUntil(sendReminders(env));
  },
};

// ---------- Telegram ----------

async function tg(env, method, params) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const d = await r.json();
  if (!d.ok && !String(d.description || "").includes("message is not modified")) console.log(method, "failed:", d.description);
  return d;
}

async function onUpdate(u, env) {
  if (u.callback_query) return onCallback(u.callback_query, env);
  const m = u.message;
  if (!m || m.chat.type !== "private") return;
  const uid = m.from.id;
  const text = (m.text || "").trim();
  if (text.startsWith("/start follow_")) {
    // pressed "🔔 Следить" in the channel before ever starting the bot
    await welcome(env, uid);
    const { text: answer } = await follow(env, uid, text.slice("/start follow_".length), false);
    return tg(env, "sendMessage", { chat_id: uid, text: answer });
  }
  if (text === "/follows" || text === FOLLOWS_BUTTON) return sendFollows(env, uid);
  if (text.startsWith("/start mood_")) {
    await env.DB.prepare("INSERT OR IGNORE INTO users (user_id, started_at) VALUES (?, ?)").bind(uid, now()).run();
    return askMood(env, uid, text.slice("/start mood_".length));
  }
  if (text === "/random" || text === RANDOM_BUTTON) return sendRandom(env, uid);
  if (text === "/later" || text === LATER_BUTTON) return sendLater(env, uid);
  if (text.startsWith("/start")) return welcome(env, uid);
  if (text === "/channel_marks_on" || text === "/channel_marks_off") {
    if (!isOwner(env, uid)) return;
    await setSetting(env, "show_in_channel", text.endsWith("on") ? "1" : "0");
    await tg(env, "sendMessage", { chat_id: uid, text: text.endsWith("on") ? "Твои отметки снова видны в канале (обновятся при следующем обзоре)." : "Отметки теперь только в личке." });
    return;
  }
  if (text.startsWith("/search")) return search(env, uid, text.slice("/search".length).trim());
  if (text && !text.startsWith("/")) return search(env, uid, text); // anything else typed is a search
}

async function welcome(env, uid) {
  await env.DB.prepare("INSERT OR IGNORE INTO users (user_id, started_at) VALUES (?, ?)").bind(uid, now()).run();
  await tg(env, "sendMessage", {
    chat_id: uid,
    parse_mode: "HTML",
    text:
      "Привет! Я присылаю карточки новых обзоров Anthony Fantano в канал " + env.CHANNEL + ".\n\n" +
      "Кнопки «Отложить», «Слушал», «Не моё» под карточками видишь только ты. " +
      "Ниже — закреплённый список свежих обзоров с твоими отметками, а всё отложенное — кнопка «" + LATER_BUTTON + "».\n\n" +
      "Кнопка «" + RANDOM_BUTTON + "» внизу выдаёт альбом с оценкой от 8, который ты ещё не отмечал(а).\n\n" +
      "Поиск: просто напиши мне артиста или альбом — найду обзоры Фантано с 2010 года.\n\n" +
      "«🔔 Следить за артистом» под карточкой: о новом обзоре этого артиста напишу сюда. Список — кнопка «" + FOLLOWS_BUTTON + "».\n\n" +
      "Неофициальный фан-проект. Не связан с Anthony Fantano и The Needle Drop.",
    reply_markup: MENU,
  });
  await refreshDmList(env, uid, true);
}

async function onCallback(q, env) {
  const uid = q.from.id;
  const parts = (q.data || "").split(":");
  let answer = "";
  let answered = false;
  // Telegram shows a spinner on the button until it's answered and drops answers that come too late, so the slow
  // follow-ups (lists, three similar cards, a card with Deezer lookups) run after the answer.
  const answerNow = async () => {
    answered = true;
    await tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: answer });
  };
  if (parts[0] === "m") {
    const [, rid, status] = parts;
    const cur = await env.DB.prepare("SELECT status FROM marks WHERE user_id=? AND review_id=?").bind(uid, rid).first();
    const next = cur && cur.status === status ? null : status;
    await setMark(env, uid, rid, next, undefined);
    answer = next ? `Отмечено: ${STATUS_LABEL[next]}` : "Отметка снята";
    await answerNow();
    if (isOwner(env, uid)) await refreshOwnerLists(env);
    else await refreshDmList(env, uid, false);
    if (next === "done") await maybeSuggestSimilar(env, uid, rid);
  } else if (parts[0] === "f") {
    const user = await env.DB.prepare("SELECT 1 FROM users WHERE user_id=?").bind(uid).first();
    // The bot can't write first to someone who never started it: open the bot, the follow is made there.
    if (!user) return tg(env, "answerCallbackQuery", { callback_query_id: q.id, url: `https://t.me/${env.BOT_USERNAME}?start=follow_${parts[1]}` });
    const res = await follow(env, uid, parts[1], true);
    answer = res.text;
    await answerNow();
    if (res.first) {
      // the first follow: say where the list is, and give people who started the bot earlier the new menu button
      await tg(env, "sendMessage", { chat_id: uid, text: `${res.text}\nСписок и отписка — кнопка «${FOLLOWS_BUTTON}» внизу.`, reply_markup: MENU });
    }
  } else if (parts[0] === "ar") {
    await answerNow();
    const r = artistReviews(await archive(env), parts[1]);
    if (r.total) await tg(env, "sendMessage", { chat_id: uid, ...artistMessage(r.artist, r.total, r.items, 0, await rankingVideo(env, r.artist)) });
  } else if (parts[0] === "da") {
    await answerNow();
    const arch = await archive(env);
    const a = arch.find((x) => x.id === parts[1]);
    if (a) await sendOtherAlbums(env, uid, arch, a.artist_name, false);
  } else if (parts[0] === "dx") {
    await answerNow();
    const arch = await archive(env);
    const a = arch.find((x) => x.id === parts[1]);
    if (a) await sendOtherAlbums(env, uid, arch, a.artist_name, true);
  } else if (parts[0] === "mb") {
    await answerNow();
    await sendMbAlbum(env, uid, parts[1], q.message);
  } else if (parts[0] === "mq") {
    await answerNow();
    await askMood(env, uid, parts[1]);
  } else if (parts[0] === "dz") {
    await answerNow();
    await sendDeezerAlbum(env, uid, parts[1]);
  } else if (parts[0] === "a") {
    await answerNow();
    const a = (await archive(env)).find((x) => x.id === parts[1]);
    if (a) await sendAlbum(env, uid, a, "");
  } else if (parts[0] === "uf") {
    const row = await env.DB.prepare("SELECT artist_name FROM follows WHERE id=? AND user_id=?").bind(Number(parts[1]), uid).first();
    if (row) await env.DB.prepare("DELETE FROM follows WHERE id=? AND user_id=?").bind(Number(parts[1]), uid).run();
    answer = row ? `Больше не следишь за ${short(row.artist_name)}` : "";
    if (q.message) await sendFollows(env, uid, q.message.message_id);
  } else if (parts[0] === "v" && parts[2] === "o") {
    // "другое": continue in the private chat, where the bot can show all four options
    return tg(env, "answerCallbackQuery", { callback_query_id: q.id, url: `https://t.me/${env.BOT_USERNAME}?start=mood_${parts[1]}` });
  } else if (parts[0] === "vo") {
    const [, rid, mi] = parts;
    const mood = MOODS[Number(mi)];
    if (mood) {
      await env.DB.prepare("INSERT INTO mood_votes (user_id, review_id, mood, vote) VALUES (?,?,?, 'y') ON CONFLICT(user_id, review_id, mood) DO UPDATE SET vote='y'").bind(uid, rid, mood).run();
      answer = `Записал: ${mood}`;
    }
  } else if (parts[0] === "v") {
    const [, rid, idx, vote] = parts;
    const r = (await reviews(env)).find((x) => x.id === rid);
    // the same rule as the card's buttons (cardMoods): the card's own guess if it has one, else the archive brief's
    const mood = cardMoods(r, r && r.ai && r.ai.moods && r.ai.moods.length ? null : await criticsOf(env, rid))[Number(idx)] || null;
    if (mood && (vote === "y" || vote === "n")) {
      await env.DB.prepare("INSERT INTO mood_votes (user_id, review_id, mood, vote) VALUES (?,?,?,?) ON CONFLICT(user_id, review_id, mood) DO UPDATE SET vote=excluded.vote")
        .bind(uid, rid, mood, vote).run();
      answer = "Голос учтён, спасибо!";
    }
  }
  if (!answered) await answerNow();
}

// ---------- marks ----------

async function setMark(env, uid, rid, status, score) {
  const cur = (await env.DB.prepare("SELECT * FROM marks WHERE user_id=? AND review_id=?").bind(uid, rid).first()) || {};
  const st = status === undefined ? cur.status ?? null : status;
  const sc = score === undefined ? cur.score ?? null : score === null ? null : Math.max(0, Math.min(10, Math.round(Number(score))));
  if (st !== null && !STATUS_LABEL[st]) throw new Error("bad status");
  const laterAt = st === "later" ? (cur.status === "later" ? cur.later_at : now()) : null;
  await env.DB.prepare(
    "INSERT INTO marks (user_id, review_id, status, score, updated_at, later_at, reminded_at) VALUES (?,?,?,?,?,?,NULL) " +
      "ON CONFLICT(user_id, review_id) DO UPDATE SET status=excluded.status, score=excluded.score, updated_at=excluded.updated_at, later_at=excluded.later_at"
  ).bind(uid, rid, st, sc, now(), laterAt).run();
}

async function userMarks(env, uid) {
  const { results } = await env.DB.prepare("SELECT review_id, status, score FROM marks WHERE user_id=?").bind(uid).all();
  const out = {};
  for (const r of results) out[r.review_id] = { status: r.status, score: r.score };
  return out;
}

function statusMap(marks) {
  const out = {};
  for (const [k, v] of Object.entries(marks)) if (v.status) out[k] = v.status;
  return out;
}

async function publicStats(env) {
  const avg = {};
  const { results } = await env.DB.prepare("SELECT review_id, AVG(score) AS avg, COUNT(score) AS n FROM marks WHERE score IS NOT NULL GROUP BY review_id").all();
  for (const r of results) avg[r.review_id] = { avg: Math.round(r.avg * 10) / 10, n: r.n };
  const moods = {};
  const v = await env.DB.prepare("SELECT review_id, mood, SUM(vote='y') AS y, SUM(vote='n') AS n FROM mood_votes GROUP BY review_id, mood").all();
  for (const r of v.results) (moods[r.review_id] ||= {})[r.mood] = { y: r.y, n: r.n };
  return { avg, moods };
}

// ---------- pinned lists ----------

async function listItems(env) {
  // GitHub Actions pushes the fresh list here after each new review; the repo copy is only a fallback.
  const cached = await getSetting(env, "list_items");
  if (cached) return JSON.parse(cached);
  const r = await fetch(env.DATA_URL.replace("reviews.json", "list.json"), { cf: { cacheTtl: 120 } });
  return r.ok ? (await r.json()).items : [];
}

async function reviews(env) {
  const r = await fetch(env.DATA_URL, { cf: { cacheTtl: 300 } });
  return r.ok ? r.json() : [];
}

// Length as Telegram counts it for the 4096 limit: visible text after HTML parsing (tags and link URLs don't count),
// in UTF-16 units, which is what a JS string's length already is.
function tgLen(html) {
  return html.replace(/<[^>]+>/g, "").replace(/&(?:[a-z]+|#\d+);/gi, "x").length;
}

function renderList(env, items, statuses) {
  const tail = env.SITE_LIVE === "1" ? `\n\n<a href="${env.SITE_URL}/">Полный список на сайте</a>` : "";
  let lines = items.map((i) => i.line + (STATUS_ICON[statuses[i.id]] || ""));
  while (lines.length && tgLen(LIST_HEAD + lines.join("\n") + tail) > MESSAGE_LIMIT) lines.pop();
  return LIST_HEAD + (lines.length ? lines.join("\n") : "Пока пусто.") + tail;
}

async function refreshDmList(env, uid, createIfMissing) {
  const user = await env.DB.prepare("SELECT dm_pinned_id FROM users WHERE user_id=?").bind(uid).first();
  if (!user) return; // the bot can't write to someone who never pressed /start
  const text = renderList(env, await listItems(env), statusMap(await userMarks(env, uid)));
  if (user.dm_pinned_id) {
    const d = await tg(env, "editMessageText", { chat_id: uid, message_id: user.dm_pinned_id, text, parse_mode: "HTML", link_preview_options: { is_disabled: true } });
    if (d.ok || String(d.description || "").includes("not modified") || !createIfMissing) return;
  } else if (!createIfMissing) return;
  const d = await tg(env, "sendMessage", { chat_id: uid, text, parse_mode: "HTML", link_preview_options: { is_disabled: true }, disable_notification: true });
  if (d.ok) {
    await tg(env, "pinChatMessage", { chat_id: uid, message_id: d.result.message_id, disable_notification: true });
    await env.DB.prepare("UPDATE users SET dm_pinned_id=? WHERE user_id=?").bind(d.result.message_id, uid).run();
  }
}

async function refreshOwnerLists(env) {
  const uid = Number(env.OWNER_ID);
  await refreshDmList(env, uid, false);
  if ((await getSetting(env, "show_in_channel")) === "0") return;
  const st = await fetch(env.DATA_URL.replace("reviews.json", "state.json"), { cf: { cacheTtl: 120 } });
  const pinned = st.ok ? (await st.json()).channel_pinned_id : null;
  if (!pinned) return;
  const text = renderList(env, await listItems(env), statusMap(await userMarks(env, uid)));
  await tg(env, "editMessageText", { chat_id: env.CHANNEL, message_id: pinned, text, parse_mode: "HTML", link_preview_options: { is_disabled: true } });
}

// ---------- archive: random pick, similar albums, mood "другое" ----------

let archiveCache = null; // kept while this Worker instance lives, so a search doesn't parse 1.4 MB every time

async function archive(env) {
  if (archiveCache && Date.now() - archiveCache.at < 600e3) return archiveCache.data;
  const r = await fetch(env.DATA_URL.replace("reviews.json", "archive.json"), { cf: { cacheTtl: 3600 } });
  if (!r.ok) return archiveCache ? archiveCache.data : [];
  archiveCache = { at: Date.now(), data: await r.json() };
  return archiveCache.data;
}

const good = (a) => !a.guest && (a.classic || (a.score != null && a.score >= 8)) && a.artist_name && a.album;
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

// The Deezer album, checked against the names ("Kid A (Remastered)" counts as "Kid A", "Muddy" doesn't as "Mud"):
// cover, track count, length and a page for every service.
async function deezerAlbum(artist, album) {
  try {
    const q = encodeURIComponent(`artist:"${artist}" album:"${album}"`);
    const r = await fetch(`https://api.deezer.com/search/album?q=${q}&limit=5`);
    const d = r.ok ? await r.json() : {};
    const want = nameKey(album);
    const hit = (d.data || []).find((x) => x.artist && nameKey(x.artist.name) === nameKey(artist) && (nameKey(x.title) === want || nameKey(x.title.replace(/\s*[([].*$/, "")) === want));
    if (!hit) return null;
    const full = await fetch(`https://api.deezer.com/album/${hit.id}`).then((x) => (x.ok ? x.json() : {})).catch(() => ({}));
    return { id: hit.id, cover: hit.cover_xl || hit.cover_big || null, link: hit.link, tracks: hit.nb_tracks || null,
             minutes: full.duration ? Math.round(full.duration / 60) : null,
             genres: ((full.genres && full.genres.data) || []).map((g) => g.name),
             year: /^\d{4}/.test(full.release_date || "") ? full.release_date.slice(0, 4) : null };
  } catch (e) {
    return null;
  }
}

// "Kid A (Remastered)" -> "Kid A"; only a trailing bracket group goes, so "(What's the Story) Morning Glory?" stays whole
const untitled = (t) => String(t || "").replace(/^["“]|["”]$/g, "").replace(/\s*[([][^)\]]*[)\]]\s*$/, "");

async function deezerJson(path) {
  try {
    const r = await fetch(`https://api.deezer.com/${path}`, { cf: { cacheTtl: 86400 } });
    return r.ok ? await r.json() : {};
  } catch (e) {
    return {};
  }
}

const UA = "LaziestMusicNerd/1.0 (https://github.com/danmnv/laziest-music-nerd)";

async function mbJson(path) {
  try {
    const r = await fetch(`https://musicbrainz.org/ws/2/${path}${path.includes("?") ? "&" : "?"}fmt=json`,
      { headers: { "User-Agent": UA, Accept: "application/json" }, cf: { cacheTtl: 86400 } });
    return r.ok ? await r.json() : null;
  } catch (e) {
    return null;
  }
}

const KIND_RU = { Live: "концерт", Compilation: "сборник", Remix: "ремиксы", Soundtrack: "саундтрек", "DJ-mix": "диджей-микс",
  Demo: "демо", "Mixtape/Street": "микстейп", Interview: "интервью", Spokenword: "речь", Audiobook: "аудиокнига" };

// An artist's releases Fantano never reviewed, from MusicBrainz: release types and first-release years there are
// reliable (Deezer mixes reissues, remixes and live albums in, and dates its own editions). main: studio albums,
// newest first, then EPs; extra: live, compilations, remixes and the like. null when MusicBrainz can't be used.
async function otherAlbums(env, arch, artistName) {
  const k = nameKey(artistName);
  // the MusicBrainz ID from a card the bot posted is certain; otherwise the best search hit with the same name
  const card = (await reviews(env)).find((r) => r.artist && r.artist.mbid && nameKey(r.artist_name) === k);
  let mbid = card && card.artist.mbid;
  if (!mbid) {
    const s = await mbJson(`artist?query=${encodeURIComponent(`artist:"${artistName}"`)}&limit=5`);
    const hit = s && (s.artists || []).find((x) => nameKey(x.name) === k);
    mbid = hit && hit.id;
  }
  if (!mbid) return null;
  // one page is 100 groups in MusicBrainz's own order, not by date: artists with many live albums need more pages
  const groups = [];
  for (let page = 0; page < 3; page++) {
    const d = await mbJson(`release-group?artist=${mbid}&type=album|ep&limit=100&offset=${page * 100}`);
    if (!d) {
      if (!page) return null;
      break;
    }
    groups.push(...(d["release-groups"] || []));
    if (groups.length >= (d["release-group-count"] || 0) || !(d["release-groups"] || []).length) break;
  }
  const reviewed = new Set(arch.filter((a) => nameKey(a.artist_name) === k).map((a) => nameKey(untitled(a.album))));
  const seen = new Set();
  const main = [], eps = [], extra = [];
  const list = groups.filter((x) => x["first-release-date"])
    .sort((a, b) => String(a["first-release-date"]).localeCompare(String(b["first-release-date"]))); // oldest first: a later live album or compilation with the same title loses
  for (const x of list) {
    const key = nameKey(untitled(x.title));
    if (!key || reviewed.has(key) || seen.has(key)) continue;
    seen.add(key);
    const second = x["secondary-types"] || [];
    const item = { id: x.id, title: x.title, year: x["first-release-date"].slice(0, 4),
                   kind: second.length ? (KIND_RU[second[0]] || second[0].toLowerCase()) : x["primary-type"] === "EP" ? "EP" : "" };
    (second.length ? extra : x["primary-type"] === "EP" ? eps : main).push(item);
  }
  return { main: main.reverse().concat(eps.reverse()), extra: extra.reverse() }; // newest first
}

// The same from Deezer, when MusicBrainz doesn't answer: albums only, one per title.
async function deezerOtherAlbums(arch, artistName) {
  const k = nameKey(artistName);
  const s = await deezerJson(`search/artist?q=${encodeURIComponent(artistName)}&limit=5`);
  const art = (s.data || []).find((x) => nameKey(x.name) === k);
  if (!art) return null;
  const d = await deezerJson(`artist/${art.id}/albums?limit=100`);
  const reviewed = new Set(arch.filter((a) => nameKey(a.artist_name) === k).map((a) => nameKey(untitled(a.album))));
  const seen = new Set();
  const out = [];
  const list = (d.data || []).filter((x) => x.record_type === "album")
    .sort((a, b) => String(a.release_date).localeCompare(String(b.release_date))); // oldest first: the original edition wins
  for (const x of list) {
    const key = nameKey(untitled(x.title));
    if (!key || reviewed.has(key) || seen.has(key)) continue;
    seen.add(key);
    out.push({ dz: x.id, title: x.title, year: String(x.release_date || "").slice(0, 4), kind: "" });
  }
  return { main: out.reverse(), extra: [] };
}

async function sendOtherAlbums(env, uid, arch, artist, extraOnly) {
  const anchor = arch.find((a) => nameKey(a.artist_name) === nameKey(artist));
  const res = (await otherAlbums(env, arch, artist)) || (extraOnly ? null : await deezerOtherAlbums(arch, artist));
  if (!res) return tg(env, "sendMessage", { chat_id: uid, text: `Не нашёл дискографию ${artist}.` });
  const items = extraOnly ? res.extra : res.main;
  if (!items.length) {
    return tg(env, "sendMessage", { chat_id: uid, text: extraOnly ? `У ${artist} больше ничего нет.` : `У ${artist} нет альбомов, которые Фантано не обозревал.` });
  }
  const shown = items.slice(0, 30);
  const rows = shown.map((x) => [{
    text: `💿 ${short(x.title)}${x.year ? " · " + x.year : ""}${x.kind ? " · " + x.kind : ""}`.slice(0, 120),
    callback_data: x.dz ? `dz:${x.dz}` : `mb:${x.id}`,
  }]);
  if (!extraOnly && res.extra.length && anchor) {
    rows.push([{ text: `Ещё: концертные, сборники, ремиксы (${res.extra.length})`, callback_data: `dx:${anchor.id}` }]);
  }
  const what = extraOnly ? "концертные, сборники, ремиксы и прочее" : "альбомы без обзора Фантано";
  return tg(env, "sendMessage", {
    chat_id: uid,
    text: `${artist} — ${what}${items.length > shown.length ? ` (показаны ${shown.length} новых из ${items.length})` : ""}:`,
    reply_markup: { inline_keyboard: rows },
  });
}

// A release from MusicBrainz: its year and type from there, cover, length and links from Deezer.
// msg: the list message the button was on; when MusicBrainz is busy, the artist, title and year are read from it.
async function sendMbAlbum(env, uid, id, msg) {
  if (!/^[0-9a-f-]{36}$/.test(id || "")) return;
  const g = await mbJson(`release-group/${id}?inc=artist-credits`);
  if (!g || !g.title) {
    const x = fromListButton(msg, `mb:${id}`);
    if (!x) return tg(env, "sendMessage", { chat_id: uid, text: "MusicBrainz сейчас не отвечает, попробуй через минуту." });
    const dz = await deezerAlbum(x.artist, untitled(x.title));
    return sendUnreviewed(env, uid, { ...x, key: id, genres: dz ? dz.genres : [], tracks: dz && dz.tracks, minutes: dz && dz.minutes,
      cover: dz && dz.cover, link: dz && dz.link });
  }
  const artist = ((g["artist-credit"] || [])[0] || {}).name || "";
  const dz = await deezerAlbum(artist, untitled(g.title));
  const second = g["secondary-types"] || [];
  const kind = second.length ? (KIND_RU[second[0]] || second[0].toLowerCase()) : g["primary-type"] === "EP" ? "EP" : "";
  return sendUnreviewed(env, uid, {
    key: id, artist, title: g.title, year: String(g["first-release-date"] || "").slice(0, 4), kind,
    genres: dz ? dz.genres : [], tracks: dz && dz.tracks, minutes: dz && dz.minutes, cover: dz && dz.cover, link: dz && dz.link,
  });
}

// "Radiohead — альбомы без обзора Фантано:" and the button "💿 The Bends · 1995 · EP" -> {artist, title, year, kind}
function fromListButton(msg, data) {
  const m = /^(.+?) — (?:альбомы без обзора|концертные)/.exec((msg && msg.text) || "");
  const b = ((msg && msg.reply_markup && msg.reply_markup.inline_keyboard) || []).flat().find((x) => x.callback_data === data);
  if (!m || !b) return null;
  const [title, ...rest] = b.text.replace(/^💿 /, "").split(" · ");
  if (!title || title.endsWith("…")) return null; // a cut title would find the wrong album
  const year = /^\d{4}$/.test(rest[0] || "") ? rest.shift() : "";
  return { artist: m[1], title, year, kind: rest[0] || "" };
}

// A card for an album without Fantano's review: cover, year, length, critics from Wikipedia, where to listen.
// If it turns out to be reviewed after all, the usual card is sent.
async function sendDeezerAlbum(env, uid, id) {
  if (!/^\d+$/.test(id || "")) return;
  const d = await deezerJson(`album/${id}`);
  if (!d.id) return tg(env, "sendMessage", { chat_id: uid, text: "Не получилось открыть этот альбом в Deezer." });
  return sendUnreviewed(env, uid, {
    key: `dz${d.id}`, artist: d.artist ? d.artist.name : "", title: d.title, year: /^\d{4}/.test(d.release_date || "") ? d.release_date.slice(0, 4) : "",
    kind: d.record_type === "ep" ? "EP" : "", genres: ((d.genres && d.genres.data) || []).map((g) => g.name),
    tracks: d.nb_tracks, minutes: d.duration ? Math.round(d.duration / 60) : null, cover: d.cover_xl || d.cover_big, link: d.link,
  });
}

async function sendUnreviewed(env, uid, x) {
  const arch = await archive(env);
  const k = nameKey(x.artist);
  const t = nameKey(untitled(x.title));
  const reviewed = t && arch.find((a) => nameKey(a.artist_name) === k && nameKey(untitled(a.album)) === t);
  if (reviewed) return sendAlbum(env, uid, reviewed, "");
  const rt = await wikiCritics(x.artist, untitled(x.title));
  const facts = [
    (x.genres || []).slice(0, 3).join(", "),
    x.kind,
    x.tracks ? tracksWord(x.tracks) : "",
    x.minutes ? `${x.minutes} мин` : "",
  ].filter(Boolean).join(" · ");
  const text = `<b>${esc(x.artist)} — ${esc(x.title)}</b>${x.year ? ` (${x.year})` : ""}\n⚪ Фантано не обозревал${facts ? " · " + esc(facts) : ""}${criticsText(rt)}`;
  const q = encodeURIComponent(`${x.artist} ${x.title}`);
  const known = arch.find((a) => nameKey(a.artist_name) === k); // any review of the artist: follow and their list work through it
  const google = { text: "🔎 Google", url: `https://www.google.com/search?q=${q}` };
  const rows = [
    [{ text: "🔎 YouTube Music", url: `https://music.youtube.com/search?q=${q}` }, x.link ? { text: "Все платформы", url: `https://album.link/${x.link}` } : google],
  ];
  rows.push(x.link ? [google, aoty(x.artist, x.title)] : [aoty(x.artist, x.title)]);
  if (x.key) {
    // remembered so that "📌 Отложенные", the reminder and "▶ Отрывки" know what this ID is
    await env.DB.prepare("INSERT INTO unreviewed (id, artist_name, album, year) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET artist_name=excluded.artist_name, album=excluded.album, year=excluded.year")
      .bind(x.key, x.artist, x.title, x.year || null).run();
    rows.push(MARK_ROW(x.key));
  }
  if (known) rows.push([{ text: "🔔 Следить", callback_data: `f:${known.id}` }, { text: "📚 Все обзоры", callback_data: `ar:${known.id}` }]);
  const reply_markup = { inline_keyboard: rows };
  if (x.cover) {
    const r = await tg(env, "sendPhoto", { chat_id: uid, photo: x.cover, caption: text, parse_mode: "HTML", reply_markup });
    if (r.ok) return r;
  }
  return tg(env, "sendMessage", { chat_id: uid, text, parse_mode: "HTML", reply_markup, link_preview_options: { is_disabled: true } });
}

// Critics' and listeners' scores on Album of the Year: a link to its search only, nothing is fetched from AOTY.
const aoty = (artist, album) => ({ text: "🔎 AOTY", url: `https://www.albumoftheyear.org/search/?q=${encodeURIComponent(`${artist} ${album}`)}` });

// A full card for one review, as in the channel: cover, score, genres, length, links, marks and "🔔".
// a: an archive entry; a review the bot posted a card for has more in reviews.json, and that is used first.
async function sendAlbum(env, uid, a, intro) {
  const full = (await reviews(env)).find((x) => x.id === a.id);
  const r = full || a;
  const links = (full && full.links) || {};
  const [dz, rt] = await Promise.all([
    (full && full.covers && full.covers.length && full.duration_min) ? null : deezerAlbum(r.artist_name, r.album),
    criticsOf(env, r.id),
  ]);
  const cover = (full && full.covers && full.covers[0]) || (dz && dz.cover);
  const tracks = (full && full.tracks && full.tracks.length) || (dz && dz.tracks);
  const minutes = (full && full.duration_min) || (dz && dz.minutes);
  // The release year; Deezer may only have a later reissue, so its year counts only if it isn't after the review.
  const reviewYear = String(r.published).slice(0, 4);
  const ofArtist = (await archive(env)).filter((x) => nameKey(x.artist_name) === nameKey(r.artist_name))
    .sort((x, y) => String(x.published).localeCompare(String(y.published)));
  const nth = ofArtist.findIndex((x) => x.id === r.id) + 1;
  const year = (full && full.year) || (dz && dz.year && dz.year <= reviewYear ? dz.year : null);
  const facts = [
    (r.genres || []).slice(0, 3).join(", "),
    tracks ? tracksWord(tracks) : "",
    minutes ? `${minutes} мин` : "",
    year ? "" : `обзор ${reviewYear}`, // the review year only when the release year is unknown
    r.guest ? "гостевой обзор" : "",
    nth && ofArtist.length > 1 ? `${nth}-й из ${ofArtist.length} обзоров артиста` : "",
  ].filter(Boolean).join(" · ");
  // the short brief: the card's own (Gemini), else the archive's (lmn/briefs.py, in rt); Fantano's line only without one
  const brief = (full && full.ai && full.ai.brief) || (rt && rt.brief);
  const moods = cardMoods(full, rt);
  const words = [
    brief ? `<b>Бриф:</b> ${esc(brief)}` : "",
    rt && rt.blurb && !brief ? `💬 <i>${esc(rt.blurb)}</i>` : "",
    rt && rt.fav && rt.fav.length ? `★ Любимые у Фантано: ${esc(rt.fav.join(", "))}` : "",
    moods.length ? `<b>Когда слушать:</b> ${esc(moods.join(" / "))} <i>(догадка ИИ, поправь кнопками)</i>` : "",
  ].filter(Boolean).map((l) => "\n" + l).join("");
  // a blank line between the score line and the words, so they don't read as one block
  const text = (intro ? intro + "\n\n" : "") + `<b>${esc(r.artist_name)} — ${esc(r.album)}</b>${year ? ` (${year})` : ""}\n${badge(r)}${facts ? " · " + esc(facts) : ""}${words ? "\n" + words : ""}${criticsText(rt)}`;
  const q = encodeURIComponent(`${r.artist_name} ${r.album}`);
  const allServices = links.songlink || (dz && dz.link ? `https://album.link/${dz.link}` : null);
  const reply_markup = { inline_keyboard: [
    [
      r.video_id ? { text: "▶ Видеообзор", url: `https://youtu.be/${r.video_id}` } : { text: "Обзор", url: r.url },
      links.youtube_album ? { text: "YouTube (альбом)", url: links.youtube_album } : { text: "🔎 YouTube Music", url: `https://music.youtube.com/search?q=${q}` },
    ],
    [...(allServices ? [{ text: "Все платформы", url: allServices }] : []), { text: "🔎 Google", url: `https://www.google.com/search?q=${q}` }, aoty(r.artist_name, r.album)],
    MARK_ROW(r.id),
    [{ text: "🔔 Следить", callback_data: `f:${r.id}` }, { text: "📚 Все обзоры", callback_data: `ar:${r.id}` }],
    // the AI's mood guess gets the channel card's vote (да / нет, «другое» asks all four); without one, a button asks
    ...moods.map((m, i) => [{ text: `${m}: да`, callback_data: `v:${r.id}:${i}:y` }, { text: "нет", callback_data: `v:${r.id}:${i}:n` }]),
    [{ text: moods.length ? "Настроение: другое" : "🕒 Когда слушать?", callback_data: `mq:${r.id}` },
      // Deezer's official player for Fantano's favourite tracks lives on the site: Telegram can't embed it, and handing
      // out the audio file is against Deezer's rules
      ...(rt && rt.fav_play && env.SITE_URL ? [{ text: "▶ Любимые треки", url: `${env.SITE_URL}/r/${encodeURIComponent(r.id)}.html#fav` }] : [])],
  ] };
  if (cover) {
    const d = await tg(env, "sendPhoto", { chat_id: uid, photo: cover, caption: text, parse_mode: "HTML", reply_markup });
    if (d.ok) return d;
  }
  return tg(env, "sendMessage", { chat_id: uid, text, parse_mode: "HTML", reply_markup, link_preview_options: { is_disabled: true } });
}

// Critic scores and charts for a review, from the site's rt/<id>.json (built from data/ratings.json; source:
// the album's Wikipedia article). null when there is none. One small fetch instead of parsing all ratings.
// The AI's mood guess for a card: the bot's own card (Gemini) first, else the archive brief's (lmn/briefs.py, in rt).
function cardMoods(full, rt) {
  const m = (full && full.ai && full.ai.moods && full.ai.moods.length ? full.ai.moods : rt && rt.moods) || [];
  return m.filter((x) => MOODS.includes(x)).slice(0, 2);
}

async function criticsOf(env, id) {
  try {
    const r = await fetch(`${env.SITE_URL}/rt/${encodeURIComponent(id)}.json`, { cf: { cacheTtl: 3600 } });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}


function albumButtons(items, withArtist) {
  return items.map((a) => [{
    text: `${badge(a)} · ${withArtist ? short(a.artist_name) + " — " : ""}${short(a.album)} · обзор ${String(a.published).slice(0, 4)}${a.guest ? " · гость" : ""}`.slice(0, 120),
    callback_data: `a:${a.id}`,
  }]);
}

function plural(n, one, few, many) {
  return n % 10 === 1 && n % 100 !== 11 ? one : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many;
}

const reviewsWord = (n) => `${n} ${plural(n, "обзор", "обзора", "обзоров")}`;
const tracksWord = (n) => `${n} ${plural(n, "трек", "трека", "треков")}`;

// One artist's reviews as buttons, newest first.
// Fantano's "Artist: Worst to Best" video for this artist, if he made one (site's wtb.json, from lmn/specials.py).
async function rankingVideo(env, artist) {
  try {
    const r = await fetch(`${env.SITE_URL}/wtb.json`, { cf: { cacheTtl: 3600 } });
    const v = r.ok ? (await r.json()).find((x) => nameKey(x.artist) === nameKey(artist)) : null;
    return v ? { text: `🎬 ${short(v.artist)}: от худшего к лучшему (${v.date.slice(0, 4)})`.slice(0, 64), url: `https://youtu.be/${v.video_id}` } : null;
  } catch {
    return null;
  }
}

function artistMessage(artist, total, items, others, video = null) {
  const head = `${artist} — ${reviewsWord(total)} Фантано` + (total > items.length ? ` (показаны ${items.length} новых)` : "") + ":";
  const tail = others ? `\n\nЕщё ${reviewsWord(others)} других артистов по этому запросу — уточни его, чтобы их увидеть.` : "";
  const more = items.length ? [[{ text: "💿 Другие альбомы (без обзора Фантано)", callback_data: `da:${items[0].id}` }]] : [];
  return { text: head + tail, reply_markup: { inline_keyboard: albumButtons(items, false).concat(more, video ? [[video]] : []) } };
}

// A search answers with a card, one artist's albums, a few albums, or a choice of artists first.
async function search(env, uid, query) {
  const r = answerSearch(await archive(env), query);
  if (r.kind === "none") {
    // no review: maybe the album exists anyway; its card then shows what's known without Fantano
    const d = await deezerJson(`search/album?q=${encodeURIComponent(query.slice(0, 100))}&limit=6`);
    const hits = (d.data || []).filter((x) => x.artist && x.record_type !== "single");
    if (hits.length) {
      return tg(env, "sendMessage", { chat_id: uid, text: `Обзора Фантано по запросу «${query.slice(0, 100)}» нет. Нашёл в Deezer:`,
        reply_markup: { inline_keyboard: hits.map((x) => [{ text: `💿 ${short(x.artist.name)} — ${short(x.title)}`.slice(0, 120), callback_data: `dz:${x.id}` }]) } });
    }
    return tg(env, "sendMessage", { chat_id: uid, text: `Не нашёл обзора Фантано по запросу «${query.slice(0, 100)}». Попробуй имя артиста или название альбома.` });
  }
  if (r.kind === "card") return sendAlbum(env, uid, r.item, "");
  if (r.kind === "albums" && r.artist) return tg(env, "sendMessage", { chat_id: uid, ...artistMessage(r.artist, r.total, r.items, r.others, await rankingVideo(env, r.artist)) });
  if (r.kind === "albums") return tg(env, "sendMessage", { chat_id: uid, text: `Нашёл ${r.total}:`, reply_markup: { inline_keyboard: albumButtons(r.items, true) } });
  return tg(env, "sendMessage", {
    chat_id: uid,
    text: `Нашёл ${reviewsWord(r.total)} у ${r.groups} ${plural(r.groups, "артиста", "артистов", "артистов")}. Выбери артиста` +
      (r.groups > r.artists.length ? ` (показаны ${r.artists.length} с наибольшим числом обзоров) или уточни запрос:` : ":"),
    reply_markup: { inline_keyboard: r.artists.map((x) => [{ text: `${short(x.name)} · ${reviewsWord(x.count)}`.slice(0, 120), callback_data: `ar:${x.id}` }]) },
  });
}

async function sendRandom(env, uid) {
  const marked = await userMarks(env, uid);
  const pool = (await archive(env)).filter((a) => good(a) && !marked[a.id]);
  if (!pool.length) return tg(env, "sendMessage", { chat_id: uid, text: "Ты отметил(а) всё, что было с оценкой от 8. Впечатляет." });
  return sendAlbum(env, uid, pick(pool), "🎲 Случайный из архива:");
}

async function maybeSuggestSimilar(env, uid, rid) {
  const user = await env.DB.prepare("SELECT 1 FROM users WHERE user_id=?").bind(uid).first();
  if (!user) return; // can't write first to someone who never started the bot
  const m = await env.DB.prepare("SELECT score FROM marks WHERE user_id=? AND review_id=?").bind(uid, rid).first();
  if (m && m.score != null && m.score < 7) return;
  const arch = await archive(env);
  const base = arch.find((a) => a.id === rid);
  if (!base || !base.genres || !base.genres.length) return;
  const marked = await userMarks(env, uid);
  const g = new Set(base.genres.map((x) => x.toLowerCase()));
  const scored = arch.filter((a) => good(a) && a.id !== rid && !marked[a.id])
    .map((a) => ({ a, n: (a.genres || []).filter((x) => g.has(x.toLowerCase())).length }))
    .filter((x) => x.n > 0);
  if (!scored.length) return;
  const best = Math.max(...scored.map((x) => x.n));
  const top = scored.filter((x) => x.n === best).map((x) => x.a);
  const chosen = [];
  while (chosen.length < 3 && top.length) chosen.push(top.splice(Math.floor(Math.random() * top.length), 1)[0]);
  await tg(env, "sendMessage", { chat_id: uid, parse_mode: "HTML", text: `Понравилось <b>${esc(base.artist_name)} — ${esc(base.album)}</b>? Вот три похожих по жанрам:` });
  for (const a of chosen) await sendAlbum(env, uid, a, "");
}

async function askMood(env, uid, rid) {
  const r = (await reviews(env)).find((x) => x.id === rid) || (await archive(env)).find((x) => x.id === rid);
  if (!r) return;
  await tg(env, "sendMessage", {
    chat_id: uid, parse_mode: "HTML",
    text: `Когда лучше слушать <b>${esc(r.artist_name)} — ${esc(r.album)}</b>?`,
    reply_markup: { inline_keyboard: MOODS.map((m, i) => [{ text: m, callback_data: `vo:${rid}:${i}` }]) },
  });
}

// ---------- following artists ----------

function short(name) {
  const s = String(name || "");
  return s.length > 80 ? s.slice(0, 79) + "…" : s;
}

async function reviewArtist(env, rid) {
  // Cards just posted are known from GitHub Actions (/api/new-reviews) before reviews.json is updated.
  const row = await env.DB.prepare("SELECT artist_name, mbid FROM review_artists WHERE review_id=?").bind(rid).first();
  if (row) return row;
  const r = (await reviews(env)).find((x) => x.id === rid) || (await archive(env)).find((x) => x.id === rid);
  return r && r.artist_name ? { artist_name: r.artist_name, mbid: (r.artist && r.artist.mbid) || null } : null;
}

// Returns {text for the person, first: whether this is their first follow}.
// toggle: a second press on the card's button stops following.
async function follow(env, uid, rid, toggle) {
  const a = await reviewArtist(env, rid);
  const key = a && nameKey(a.artist_name);
  if (!key) return { text: "Не нашёл артиста этого обзора." };
  const cur = await env.DB.prepare("SELECT id FROM follows WHERE user_id=? AND name_key=?").bind(uid, key).first();
  if (cur && toggle) {
    await env.DB.prepare("DELETE FROM follows WHERE id=?").bind(cur.id).run();
    return { text: `Больше не следишь за ${short(a.artist_name)}.` };
  }
  let first = false;
  if (!cur) {
    first = !(await env.DB.prepare("SELECT 1 FROM follows WHERE user_id=?").bind(uid).first());
    await env.DB.prepare("INSERT INTO follows (user_id, name_key, mbid, artist_name, created_at) VALUES (?,?,?,?,?)")
      .bind(uid, key, a.mbid || null, a.artist_name, now()).run();
  }
  return { text: `🔔 Ты следишь за ${short(a.artist_name)}. О новом обзоре напишу в личку.`, first };
}

async function sendFollows(env, uid, editId) {
  const { results } = await env.DB.prepare("SELECT id, artist_name FROM follows WHERE user_id=? ORDER BY artist_name COLLATE NOCASE").bind(uid).all();
  const text = results.length
    ? "<b>Ты следишь за:</b>\n" + results.map((f) => "• " + esc(f.artist_name)).join("\n") + "\n\nНажми на артиста ниже, чтобы перестать следить."
    : "Ты пока ни за кем не следишь. Нажми «🔔 Следить за артистом» под карточкой в канале.";
  const reply_markup = { inline_keyboard: results.slice(0, 90).map((f) => [{ text: `✗ ${short(f.artist_name)}`, callback_data: `uf:${f.id}` }]) };
  if (editId) return tg(env, "editMessageText", { chat_id: uid, message_id: editId, text, parse_mode: "HTML", reply_markup });
  return tg(env, "sendMessage", { chat_id: uid, text, parse_mode: "HTML", reply_markup });
}

// r: {id, artist_name, mbid, album, score, msg} from GitHub Actions. Returns how many people were messaged.
// Each person hears about a review once, however often Actions retries.
async function tellFollowers(env, r) {
  if (!r || !r.id || !r.artist_name) return 0;
  const rid = String(r.id);
  await env.DB.prepare("INSERT INTO review_artists (review_id, artist_name, mbid) VALUES (?,?,?) " +
    "ON CONFLICT(review_id) DO UPDATE SET artist_name=excluded.artist_name, mbid=excluded.mbid").bind(rid, r.artist_name, r.mbid || null).run();
  const { results } = await env.DB.prepare("SELECT user_id, name_key, mbid FROM follows WHERE name_key=? OR mbid=?")
    .bind(nameKey(r.artist_name), r.mbid || "").all();
  const post = r.msg ? `https://t.me/${String(env.CHANNEL).replace(/^@/, "")}/${r.msg}` : null;
  let sent = 0;
  for (const f of results) {
    if (!followMatches(f, r)) continue;
    const ins = await env.DB.prepare("INSERT OR IGNORE INTO follow_sent (user_id, review_id, sent_at) VALUES (?,?,?)").bind(f.user_id, rid, now()).run();
    if (!ins.meta || !ins.meta.changes) continue;
    const d = await tg(env, "sendMessage", {
      chat_id: f.user_id, parse_mode: "HTML",
      text: `🔔 Новый обзор: <b>${esc(r.artist_name)} — ${esc(r.album)}</b>${r.score ? ", " + esc(r.score) : ""}`,
      ...(post ? { reply_markup: { inline_keyboard: [[{ text: "Карточка в канале", url: post }]] } } : {}),
    });
    if (d.ok) sent++;
  }
  return sent;
}

// ---------- digest (Sunday cron, every second Sunday, see digest.mjs) ----------

async function sendDigest(env) {
  if (!isDigestSunday(new Date())) return;
  const since = new Date(Date.now() - 14 * 864e5).toISOString();
  const top = (await reviews(env)).filter((r) => r.published >= since && !r.guest && (r.classic || (r.score != null && r.score >= 8)))
    .sort((a, b) => (b.score || 10) - (a.score || 10));
  if (!top.length) return; // nothing worth sending
  const site = env.SITE_LIVE === "1";
  const lines = top.map((r) => `🟢 ${r.classic ? "CLASSIC" : r.score} · <a href="${site ? `${env.SITE_URL}/r/${r.id}.html` : r.url}">${esc(r.artist_name)} — ${esc(r.album)}</a>`);
  const text = "<b>Лучшее за две недели</b>\n\n" + lines.join("\n");
  const { results } = await env.DB.prepare("SELECT user_id FROM users").all();
  for (const u of results) await tg(env, "sendMessage", { chat_id: u.user_id, text, parse_mode: "HTML", link_preview_options: { is_disabled: true } });
}

// ---------- "📌 Отложенные" and "▶ Отрывки" ----------

// What marked IDs are: a review (archive), or an album without one (a MusicBrainz release group, or "dz<Deezer id>").
// -> { id: { artist_name, album, open: the callback that opens its card } }
async function markedNames(env, ids) {
  const out = {};
  if (!ids.length) return out;
  const want = new Set(ids);
  for (const a of await archive(env)) if (want.has(a.id)) out[a.id] = { artist_name: a.artist_name, album: a.album, open: `a:${a.id}` };
  for (const r of await reviews(env)) if (want.has(r.id) && !out[r.id]) out[r.id] = { artist_name: r.artist_name, album: r.album, open: `a:${r.id}` };
  const rest = ids.filter((id) => !out[id]);
  for (let i = 0; i < rest.length; i += 50) {
    const part = rest.slice(i, i + 50);
    const { results } = await env.DB.prepare(`SELECT id, artist_name, album FROM unreviewed WHERE id IN (${part.map(() => "?").join(",")})`).bind(...part).all();
    for (const u of results) out[u.id] = { artist_name: u.artist_name, album: u.album, open: u.id.startsWith("dz") ? `dz:${u.id.slice(2)}` : `mb:${u.id}` };
  }
  return out;
}

async function sendLater(env, uid) {
  const { results } = await env.DB.prepare("SELECT review_id FROM marks WHERE user_id=? AND status='later' ORDER BY later_at DESC").bind(uid).all();
  if (!results.length) {
    return tg(env, "sendMessage", { chat_id: uid, text: "Отложенного нет. Нажми «• Отложить» под любой карточкой, и альбом появится здесь." });
  }
  const names = await markedNames(env, results.map((r) => r.review_id));
  const items = results.map((r) => names[r.review_id]).filter(Boolean);
  const shown = items.slice(0, 40);
  return tg(env, "sendMessage", {
    chat_id: uid,
    text: `Отложено: ${items.length}${items.length > shown.length ? ` (показаны ${shown.length} последних)` : ""}. Через 3 недели напомню о каждом, не чаще раза в неделю.`,
    reply_markup: { inline_keyboard: shown.map((x) => [{ text: `• ${short(x.artist_name)} — ${short(x.album)}`.slice(0, 120), callback_data: x.open }]) },
  });
}

// ---------- reminders (daily cron) ----------

async function sendReminders(env) {
  const cutoff = new Date(Date.now() - 21 * 864e5).toISOString();
  const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString();
  const { results } = await env.DB.prepare(
    "SELECT m.user_id, m.review_id FROM marks m JOIN users u ON u.user_id=m.user_id " +
      "WHERE m.status='later' AND m.later_at <= ? AND m.reminded_at IS NULL " +
      "AND NOT EXISTS (SELECT 1 FROM marks x WHERE x.user_id=m.user_id AND x.reminded_at > ?) ORDER BY m.later_at"
  ).bind(cutoff, weekAgo).all();
  if (!results.length) return;
  const names = await markedNames(env, results.map((r) => r.review_id));
  const done = new Set();
  for (const row of results) {
    if (done.has(row.user_id)) continue; // at most one reminder per person per run, and per week by the query
    const r = names[row.review_id];
    if (!r) continue;
    await tg(env, "sendMessage", {
      chat_id: row.user_id,
      parse_mode: "HTML",
      text: `Три недели назад <b>${esc(r.artist_name)} — ${esc(r.album)}</b> ушёл в «отложено». Самое время послушать?`,
      reply_markup: { inline_keyboard: [[{ text: "✓ Слушал", callback_data: `m:${row.review_id}:done` }, { text: "Открыть", callback_data: r.open }]] },
    });
    await env.DB.prepare("UPDATE marks SET reminded_at=? WHERE user_id=? AND review_id=?").bind(now(), row.user_id, row.review_id).run();
    done.add(row.user_id);
  }
}

// ---------- site login (Telegram Login Widget) ----------

async function login(data, env) {
  const { hash, ...fields } = data || {};
  if (!hash || !fields.id || !fields.auth_date) return json({ error: "bad request" }, 400);
  if (Date.now() / 1000 - Number(fields.auth_date) > 86400) return json({ error: "expired" }, 401);
  const check = Object.keys(fields).sort().map((k) => `${k}=${fields[k]}`).join("\n");
  const secret = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(env.TELEGRAM_BOT_TOKEN));
  if ((await hmacHex(secret, check)) !== hash) return json({ error: "bad hash" }, 401);
  // We keep only the Telegram ID; name and photo are not stored.
  const exp = Math.floor(Date.now() / 1000) + 90 * 86400;
  const payload = `${fields.id}.${exp}`;
  const sig = await hmacHex(new TextEncoder().encode(env.SESSION_SECRET), payload);
  return json({ token: `${payload}.${sig}`, owner: isOwner(env, Number(fields.id)) });
}

async function sessionUser(req, env) {
  const t = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  const [id, exp, sig] = t.split(".");
  if (!id || !exp || !sig || Number(exp) < Date.now() / 1000) return null;
  const ok = (await hmacHex(new TextEncoder().encode(env.SESSION_SECRET), `${id}.${exp}`)) === sig;
  return ok ? Number(id) : null;
}

async function hmacHex(keyBytes, msg) {
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------- helpers ----------

function isOwner(env, uid) {
  return env.OWNER_ID && Number(env.OWNER_ID) === Number(uid);
}

async function getSetting(env, key) {
  const r = await env.DB.prepare("SELECT value FROM settings WHERE key=?").bind(key).first();
  return r ? r.value : null;
}

async function setSetting(env, key, value) {
  await env.DB.prepare("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(key, value).run();
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json; charset=utf-8" } });
}

function cors(env, resp) {
  const h = new Headers(resp.headers);
  h.set("Access-Control-Allow-Origin", new URL(env.SITE_URL).origin);
  h.set("Access-Control-Allow-Headers", "Authorization, Content-Type");
  h.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  return new Response(resp.body, { status: resp.status, headers: h });
}

function esc(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function now() {
  return new Date().toISOString();
}
