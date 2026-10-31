// Laziest Music Nerd — Cloudflare Worker.
// Handles Telegram button presses and /start, site login (Telegram Login Widget), personal marks,
// and a daily cron for "later" reminders. Personal marks are visible only to their owner.

import { isDigestSunday } from "./digest.mjs";

const STATUS_LABEL = { later: "• отложено", done: "✓ прослушано", nope: "✗ не понравилось" };
const STATUS_ICON = { later: " •", done: " ✓", nope: " ✗" };
const LIST_HEAD = "<b>Свежие обзоры Фантано за 60 дней</b>\n\n";
const MESSAGE_LIMIT = 4096;
const MOODS = ["для тренировки", "для настроения", "для работы за столом", "для тусовки"];
const RANDOM_BUTTON = "🎲 Случайный из архива";
const MENU = { keyboard: [[{ text: RANDOM_BUTTON }]], resize_keyboard: true, is_persistent: true };

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
  if (text.startsWith("/start mood_")) {
    await env.DB.prepare("INSERT OR IGNORE INTO users (user_id, started_at) VALUES (?, ?)").bind(uid, now()).run();
    return askMood(env, uid, text.slice("/start mood_".length));
  }
  if (text === "/random" || text === RANDOM_BUTTON) return sendRandom(env, uid);
  if (text.startsWith("/start")) {
    await env.DB.prepare("INSERT OR IGNORE INTO users (user_id, started_at) VALUES (?, ?)").bind(uid, now()).run();
    await tg(env, "sendMessage", {
      chat_id: uid,
      parse_mode: "HTML",
      text:
        "Привет! Я присылаю карточки новых обзоров Anthony Fantano в канал " + env.CHANNEL + ".\n\n" +
        "Кнопки «Отложить», «Прослушано», «Не понравилось» под карточками видишь только ты. " +
        "Ниже — закреплённый список свежих обзоров с твоими отметками.\n\n" +
        "Кнопка «" + RANDOM_BUTTON + "» внизу выдаёт альбом с оценкой от 8, который ты ещё не отмечал(а).\n\n" +
        "Неофициальный фан-проект. Не связан с Anthony Fantano и The Needle Drop.",
      reply_markup: MENU,
    });
    await refreshDmList(env, uid, true);
    return;
  }
  if (text === "/channel_marks_on" || text === "/channel_marks_off") {
    if (!isOwner(env, uid)) return;
    await setSetting(env, "show_in_channel", text.endsWith("on") ? "1" : "0");
    await tg(env, "sendMessage", { chat_id: uid, text: text.endsWith("on") ? "Твои отметки снова видны в канале (обновятся при следующем обзоре)." : "Отметки теперь только в личке." });
  }
}

async function onCallback(q, env) {
  const uid = q.from.id;
  const parts = (q.data || "").split(":");
  let answer = "";
  if (parts[0] === "m") {
    const [, rid, status] = parts;
    const cur = await env.DB.prepare("SELECT status FROM marks WHERE user_id=? AND review_id=?").bind(uid, rid).first();
    const next = cur && cur.status === status ? null : status;
    await setMark(env, uid, rid, next, undefined);
    answer = next ? `Отмечено: ${STATUS_LABEL[next]}` : "Отметка снята";
    if (isOwner(env, uid)) await refreshOwnerLists(env);
    else await refreshDmList(env, uid, false);
    if (next === "done") await maybeSuggestSimilar(env, uid, rid);
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
    const mood = r && r.ai && r.ai.moods ? r.ai.moods[Number(idx)] : null;
    if (mood && (vote === "y" || vote === "n")) {
      await env.DB.prepare("INSERT INTO mood_votes (user_id, review_id, mood, vote) VALUES (?,?,?,?) ON CONFLICT(user_id, review_id, mood) DO UPDATE SET vote=excluded.vote")
        .bind(uid, rid, mood, vote).run();
      answer = "Голос учтён, спасибо!";
    }
  }
  await tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: answer });
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

function renderList(env, items, statuses) {
  const tail = env.SITE_LIVE === "1" ? `\n\n<a href="${env.SITE_URL}/">Полный список на сайте</a>` : "";
  let lines = items.map((i) => i.line + (STATUS_ICON[statuses[i.id]] || ""));
  while (lines.length && (LIST_HEAD + lines.join("\n") + tail).length > MESSAGE_LIMIT) lines.pop();
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

async function archive(env) {
  const r = await fetch(env.DATA_URL.replace("reviews.json", "archive.json"), { cf: { cacheTtl: 3600 } });
  return r.ok ? r.json() : [];
}

const good = (a) => !a.guest && (a.classic || (a.score != null && a.score >= 8)) && a.artist_name && a.album;
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

function albumMessage(a, intro) {
  const sc = a.classic ? "CLASSIC" : `${a.score}/10`;
  const q = encodeURIComponent(`${a.artist_name} ${a.album}`);
  return {
    parse_mode: "HTML",
    text: `${intro}\n\n🟢 ${sc} · <b>${esc(a.artist_name)} — ${esc(a.album)}</b> (${a.published.slice(0, 4)})` +
      (a.genres && a.genres.length ? `\n${esc(a.genres.slice(0, 3).join(", "))}` : ""),
    reply_markup: { inline_keyboard: [
      [{ text: "Обзор", url: a.url }, { text: "YouTube Music", url: `https://music.youtube.com/search?q=${q}` }],
      [{ text: "• Отложить", callback_data: `m:${a.id}:later` }, { text: "✓ Прослушано", callback_data: `m:${a.id}:done` }, { text: "✗ Не понравилось", callback_data: `m:${a.id}:nope` }],
    ] },
  };
}

async function sendRandom(env, uid) {
  const marked = await userMarks(env, uid);
  const pool = (await archive(env)).filter((a) => good(a) && !marked[a.id]);
  if (!pool.length) return tg(env, "sendMessage", { chat_id: uid, text: "Ты отметил(а) всё, что было с оценкой от 8. Впечатляет." });
  return tg(env, "sendMessage", { chat_id: uid, ...albumMessage(pick(pool), "Случайный из архива:") });
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
  for (const a of chosen) await tg(env, "sendMessage", { chat_id: uid, ...albumMessage(a, "") });
}

async function askMood(env, uid, rid) {
  const r = (await reviews(env)).find((x) => x.id === rid);
  if (!r) return;
  await tg(env, "sendMessage", {
    chat_id: uid, parse_mode: "HTML",
    text: `Когда лучше слушать <b>${esc(r.artist_name)} — ${esc(r.album)}</b>?`,
    reply_markup: { inline_keyboard: MOODS.map((m, i) => [{ text: m, callback_data: `vo:${rid}:${i}` }]) },
  });
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
  const all = await reviews(env);
  const done = new Set();
  for (const row of results) {
    if (done.has(row.user_id)) continue; // at most one reminder per person per run, and per week by the query
    const r = all.find((x) => x.id === row.review_id);
    if (!r) continue;
    await tg(env, "sendMessage", {
      chat_id: row.user_id,
      parse_mode: "HTML",
      text: `Три недели назад <b>${esc(r.artist_name)} — ${esc(r.album)}</b> ушёл в «отложено». Самое время послушать?`,
      reply_markup: { inline_keyboard: [[{ text: "✓ Прослушано", callback_data: `m:${r.id}:done` }, { text: "Обзор", url: r.url }]] },
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
