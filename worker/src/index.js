// Laziest Music Nerd — Cloudflare Worker.
// Handles Telegram button presses and /start, site login (Telegram Login Widget), personal marks,
// following artists, and a daily cron for "later" reminders. Personal marks are visible only to their owner.

import { isDigestSunday } from "./digest.mjs";
import { nameKey, followMatches } from "./follow.mjs";
import { answerSearch, artistReviews, badge } from "./search.mjs";
import { criticsText } from "./critics.mjs";
import { wikiCritics } from "./wiki.mjs";
import { startLink, openFromStart } from "./links.mjs";
import { PAGE, OLD_DAYS, QFROM_MINUTES, lastHeard, after, before, nextAfter, laterReviews, daysOld, line as queueLine } from "./queue.mjs";
import { searchArchive } from "./search.mjs";
import { genresOf } from "./genres.mjs";
import { creditedNames, selfTitled, pickAlbum } from "./deezer.mjs";
import { untitled, sortOut, quietHour, ruDate, RECHECK_HOURS } from "./releases.mjs";

// «later» is shown as «Послушать потом» since 2026-11-02 (the owner: «может быть отложенное должно называться послушать потом»)
const STATUS_LABEL = { later: "⏳ послушать потом", done: "✓ прослушано", nope: "✗ не понравилось" };
const STATUS_ICON = { later: " ⏳", done: " ✓", nope: " ✗" };
const LIST_HEAD = "<b>Последние 30 обзоров Фантано</b>\n\n"; // the channel's pinned list (lmn/card.py LIST_HEAD)
const MESSAGE_LIMIT = 4096;
const CAPTION_LIMIT = 1024; // a photo's caption
// The stored mood words. The order is fixed: buttons carry the index (old messages too), votes store the words; words are
// only appended. The same list is lmn/gemini.py MOODS (a test keeps them equal).
const MOODS = ["для тренировки", "для настроения", "для работы за столом", "для тусовки", "в дорогу", "на прогулку", "ночью",
  "перед сном", "когда грустно", "когда злишься", "в наушниках, вдумчиво", "фоном", "для романтики", "для бодрости",
  "фоном для работы"];
// «Вайб для» since 2026-11-02 (owner, instead of «Когда слушать», which hints at a time): the moods offered and shown,
// in this order, as the words after «Вайб для». «для настроения», «ночью» and «для бодрости» are retired; «для работы за
// столом» and «фоном» count as «фоном для работы» (MOOD_ALIAS). The same in lmn/gemini.py and site_src/app.js (a test).
const VIBES = { "для тренировки": "тренировки", "фоном для работы": "фона за работой", "для тусовки": "тусовки",
  "в дорогу": "дороги", "на прогулку": "прогулки", "перед сном": "сна", "когда грустно": "грусти",
  "когда злишься": "злости", "в наушниках, вдумчиво": "вдумчивого слушания", "для романтики": "романтики" };
const MOOD_ALIAS = { "для работы за столом": "фоном для работы", "фоном": "фоном для работы" };
// stored words → the ones shown now: old words merged, retired ones dropped, no repeats (lmn/gemini.py shown_moods)
const shownMoods = (ms) => [...new Set((ms || []).map((m) => MOOD_ALIAS[m] || m).filter((m) => VIBES[m]))];
const vibe = (m) => VIBES[MOOD_ALIAS[m] || m] || m;
// Genre words → the situations they suggest, best first. For albums with no AI guess. A word matches at the start of
// a word in the tag ("metalcore", "rapper", "gothic"), not inside one: TND tags hold artist names too ("macklemore",
// "brockhampton"). The first group a tag matches wins, so the more specific groups come first.
const GENRE_MOODS = [
  [["shoegaze", "dream pop", "post-rock", "post-punk", "darkwave", "goth", "trip hop"], ["ночью", "на прогулку", "в наушниках, вдумчиво", "когда грустно"]],
  [["hip hop", "rap", "trap", "drill", "grime", "boom bap"], ["в дорогу", "для тренировки", "для тусовки", "для бодрости"]],
  [["dance", "house", "techno", "disco", "edm", "electropop", "synthpop", "club", "hyperpop", "funk", "microhouse"], ["для тусовки", "для бодрости", "для тренировки", "в дорогу"]],
  [["metal", "hardcore", "punk", "grind", "thrash", "industrial", "sludge", "crust", "synthpunk"], ["для тренировки", "когда злишься", "в дорогу", "для бодрости"]],
  [["ambient", "drone", "new age", "classical", "minimal"], ["перед сном", "для работы за столом", "фоном", "в наушниках, вдумчиво"]],
  [["electronic", "idm", "glitch"], ["в наушниках, вдумчиво", "для работы за столом", "ночью", "для тусовки"]],
  [["r&b", "soul", "neo-soul", "quiet storm"], ["для романтики", "ночью", "фоном", "на прогулку"]],
  [["folk", "singer-songwriter", "country", "slowcore", "sadcore", "emo", "acoustic", "chamber"], ["когда грустно", "на прогулку", "перед сном", "в наушниках, вдумчиво"]],
  [["jazz", "lounge", "bossa"], ["для работы за столом", "ночью", "фоном", "для романтики"]],
  [["experimental", "noise", "avant", "art ", "psychedelic", "progressive", "krautrock"], ["в наушниках, вдумчиво", "ночью", "когда злишься", "в дорогу"]],
  [["rock", "indie", "grunge", "garage", "pop"], ["в дорогу", "на прогулку", "для бодрости", "для тусовки"]],
];
const GENRE_RES = GENRE_MOODS.map(([words, moods]) =>
  [new RegExp(`[\\s-](${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`), moods]);
const DEFAULT_MOODS = ["на прогулку", "в дорогу", "в наушниках, вдумчиво", "фоном"];
const RANDOM_BUTTON = "🎲 Случайный из архива";
const FOLLOWS_BUTTON = "🔔 Мои артисты";
const LATER_BUTTON = "⏳ Послушать потом";
const OLD_LATER_BUTTON = "📌 Отложенные"; // keyboards sent before 2026-11-02 still send it
const LIKED_BUTTON = "♥ Понравившееся";
const QUEUE_BUTTON = "▶ Наверстать"; // was «▶ Дослушать» until 2026-11-02 (the owner: sounds odd)
const OLD_QUEUE_BUTTON = "▶ Дослушать"; // keyboards sent before then still send it
const HELP_BUTTON = "❓ Как пользоваться";
const MENU = { keyboard: [[{ text: QUEUE_BUTTON }, { text: RANDOM_BUTTON }], [{ text: LATER_BUTTON }, { text: LIKED_BUTTON }],
  [{ text: FOLLOWS_BUTTON }, { text: HELP_BUTTON }]],
  resize_keyboard: true, is_persistent: true };
const MENU_V = "4"; // a person whose keyboard is older gets the new one with a one-line note on their next message
// the commands in Telegram's own menu button (setMyCommands, once per COMMANDS_V, from the daily cron)
const COMMANDS = [{ command: "listen", description: "Наверстать: обзоры после последнего прослушанного" },
  { command: "random", description: "Случайный альбом из архива с оценкой от 8" }, { command: "later", description: "Послушать потом" },
  { command: "liked", description: "Понравившееся" },
  { command: "follows", description: "Мои артисты" }, { command: "help", description: "Как пользоваться ботом" },
  { command: "forget", description: "Удалить всё, что бот знает обо мне" }];
const COMMANDS_V = "4";
// Two buttons a row, short enough for a phone without "…". «♡ Понравилось» is its own mark, kept whatever the status
// (owner, 2026-11-02: «Слушал» used to overwrite «отложено», which he used for the albums he liked); ♥ when it's on.
const likeButton = (id, liked) => ({ text: liked ? "♥ Понравилось" : "♡ Понравилось", callback_data: `lk:${id}` });
const MARK_ROWS = (id, liked) => [[{ text: "✓ Слушал", callback_data: `m:${id}:done` }, likeButton(id, liked)],
  [{ text: "⏳ Послушать потом", callback_data: `m:${id}:later` }, { text: "✗ Не моё", callback_data: `m:${id}:nope` }]];

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
        // null clears (a second press of the same mark, «—» for the score); a missing field keeps what is there
        await setMark(env, uid, String(b.review_id), "status" in b ? b.status : undefined, "score" in b ? b.score : undefined);
        const later = b.status === "later";
        ctx.waitUntil(isOwner(env, uid) ? refreshOwnerLists(env) : dropDmPin(env, uid));
        return cors(env, json({ ok: true }));
      }
      if (url.pathname === "/api/refresh-lists" && req.method === "POST") {
        // Called by GitHub Actions after a new review: refresh every pinned list in private chats.
        if (req.headers.get("Authorization") !== `Bearer ${env.ACTIONS_SECRET}`) return new Response("forbidden", { status: 403 });
        const body = await req.json().catch(() => ({}));
        // The pinned lists in private chats hold each person's «отложено» now, which a new review doesn't change.
        if (Array.isArray(body.items)) await setSetting(env, "list_items", JSON.stringify(body.items));
        return json({ ok: true });
      }
      if (url.pathname === "/api/new-reviews" && req.method === "POST") {
        // Called by GitHub Actions right after cards are posted: remember each card's artist, message the followers.
        if (req.headers.get("Authorization") !== `Bearer ${env.ACTIONS_SECRET}`) return new Response("forbidden", { status: 403 });
        const body = await req.json().catch(() => ({}));
        // in portions (FOLLOW_BUDGET): a review whose followers didn't all fit is listed in `pending`, and GitHub Actions
        // sends it again with its next check
        const budget = { left: FOLLOW_BUDGET };
        let sent = 0;
        const pending = [];
        for (const r of Array.isArray(body.reviews) ? body.reviews : []) {
          const x = await tellFollowers(env, r, budget);
          sent += x.sent;
          if (!x.done) pending.push(String(r.id));
        }
        return json({ ok: true, sent, pending });
      }
      if (url.pathname === "/api/owner/id") {
        // For GitHub Actions' test mode and key check: once the webhook is set, Telegram's getUpdates is closed to them.
        if (req.headers.get("Authorization") !== `Bearer ${env.ACTIONS_SECRET}`) return new Response("forbidden", { status: 403 });
        return json({ owner_id: env.OWNER_ID ? Number(env.OWNER_ID) : null });
      }
      if (url.pathname === "/api/owner/apple") {
        // For the doctor (python -m lmn.doctor): does Apple's search answer the Worker, and what does it find
        if (req.headers.get("Authorization") !== `Bearer ${env.ACTIONS_SECRET}`) return new Response("forbidden", { status: 403 });
        const r = await appleSearch(url.searchParams.get("q") || "Radiohead Kid A");
        const body = await r.text();
        return json({ status: r.status, type: r.headers.get("content-type"), start: body.slice(0, 300),
                      found: await appleAlbum("Radiohead", "Kid A") });
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
    // «Лучшее за две недели» is off for now (owner, 2026-11-02); DIGEST = "1" in wrangler.toml turns it back on
    if (event.cron === "0 7 * * SUN") { if (env.DIGEST === "1") ctx.waitUntil(sendDigest(env)); }
    else if (event.cron === RELEASES_CRON) ctx.waitUntil(watchReleases(env, new Date(event.scheduledTime || Date.now())));
    else ctx.waitUntil((async () => {
      const budget = { left: DAILY_BUDGET - 3 }; // setCommands: a setting, and when the commands change, Telegram and a setting
      await setCommands(env);
      await sendReminders(env, budget);
      await migrateDmPins(env, budget);
    })());
  },
};

// ---------- Telegram ----------

// Telegram's own menu of commands, set once per COMMANDS_V from the daily cron.
async function setCommands(env) {
  if ((await getSetting(env, "commands_v")) === COMMANDS_V) return;
  const d = await tg(env, "setMyCommands", { commands: COMMANDS });
  if (d.ok) await setSetting(env, "commands_v", COMMANDS_V);
}

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
  if (!text.startsWith("/start")) await maybeNewMenu(env, uid);
  if (text === "/help" || text === HELP_BUTTON) return sendHelp(env, uid);
  if (text === "/forget") return askForget(env, uid);
  if (text === "/listen" || text === QUEUE_BUTTON || text === OLD_QUEUE_BUTTON) return sendQueue(env, uid, {});
  if (text === "/random" || text === RANDOM_BUTTON) return sendRandom(env, uid);
  if (text === "/later" || text === LATER_BUTTON || text === OLD_LATER_BUTTON) return sendLater(env, uid);
  if (text === "/liked" || text === LIKED_BUTTON) return sendLiked(env, uid);
  const open = openFromStart(text);
  if (open) {
    // an album tapped in a pinned list (the channel's or this chat's): its card here. Telegram sent "/start …" for the
    // tap; it is removed so the chat holds only cards.
    const known = await env.DB.prepare("SELECT 1 FROM users WHERE user_id=?").bind(uid).first();
    if (!known) await welcome(env, uid);
    else await tg(env, "deleteMessage", { chat_id: uid, message_id: m.message_id });
    return openCard(env, uid, open);
  }
  if (text.startsWith("/start")) return welcome(env, uid);
  if (text === "/channel_marks_on" || text === "/channel_marks_off") {
    if (!isOwner(env, uid)) return;
    await setSetting(env, "show_in_channel", text.endsWith("on") ? "1" : "0");
    await tg(env, "sendMessage", { chat_id: uid, text: text.endsWith("on") ? "Твои отметки снова видны в канале (обновятся при следующем обзоре)." : "Отметки теперь только в личке." });
    return;
  }
  if (text && !text.startsWith("/") && (await queueFrom(env, uid, text))) return; // the answer to «после какого альбома?»
  if (text.startsWith("/search")) return search(env, uid, text.slice("/search".length).trim());
  if (text && !text.startsWith("/")) return search(env, uid, text); // anything else typed is a search
}

async function welcome(env, uid) {
  await env.DB.prepare("INSERT OR IGNORE INTO users (user_id, started_at) VALUES (?, ?)").bind(uid, now()).run();
  const channel = String(env.CHANNEL || "").replace(/^@/, "");
  await tg(env, "sendMessage", {
    chat_id: uid,
    parse_mode: "HTML",
    link_preview_options: { is_disabled: true },
    text: "Привет! Здесь мы знакомимся с новой музыкой, отталкиваясь от обзоров Anthony Fantano.\n\n" + helpText(env),
    reply_markup: MENU,
  });
  await setSetting(env, `menu:${uid}`, MENU_V);
  await dropDmPin(env, uid);
}

function helpText(env) {
  const channel = String(env.CHANNEL || "").replace(/^@/, "");
  // The owner's wording, 2026-11-02: the channel brings the new releases, the bot finds and explains; no ✓/✗ in the text
  // where you are, first: the bot and the channel are two tools that work as a pair
  return "<b>Ты сейчас в боте.</b> Он работает в паре с каналом " + `<a href="https://t.me/${channel}">@${channel}</a>` +
    ": в канале выходят карточки новых обзоров, а здесь можно найти любой альбом и узнать о нём всё. " +
    "В закреплённом в канале 30 последних обзоров: нажми на альбом, и я пришлю его карточку сюда.\n\n" +
    "<b>Здесь</b> всё твоё личное:\n" +
    "• <b>Поиск.</b> Просто отправь сюда название группы или альбома, и я покажу всё, что о нём собрано: описание, оценки, треклист и ссылки, где послушать. Найдутся и альбомы, которые Фантано не обозревал.\n" +
    "• <b>Наверстать.</b> «" + QUEUE_BUTTON + "»: сверху альбомы из «" + LATER_BUTTON + "», ниже обзоры, которые вышли после места, где ты остановился(-ась), по " + PAGE + " за раз. Нажми на альбом, послушай, нажми «Послушал → дальше», и придёт следующий. «⏳ Потом → дальше» поднимет альбом наверх списка, «Пропустить →» просто пропустит, «← Назад» вернёт предыдущий.\n" +
    "• <b>Послушать потом.</b> «⏳ Послушать потом» под карточкой, в канале или здесь: альбом попадёт в список «" + LATER_BUTTON + "» и наверх «Наверстать». Через 3 недели напомню.\n" +
    "• <b>Понравилось.</b> «♡ Понравилось» под карточкой: альбом попадёт в список «" + LIKED_BUTTON + "», чтобы потом скачать или купить. Это отдельная отметка, «Слушал» её не стирает, так что можно нажать обе.\n" +
    "• <b>Отметки.</b> «Слушал», «Понравилось», «Послушать потом», «Не моё»: кнопки видят все, а твои отметки только ты. На сайте они видны после входа через Telegram.\n" +
    "• <b>Артисты.</b> «🔔 Следить» под карточкой: когда у артиста выйдет новый альбом, а потом обзор Фантано на него, напишу сюда. Список — кнопка «" + FOLLOWS_BUTTON + "».\n" +
    "• <b>Случайный.</b> «" + RANDOM_BUTTON + "»: альбом с оценкой от 8, который ты ещё не отмечал(а).\n\n" +
    // what is stored, what for and how to remove it, as short as it can be (the owner, 2026-11-02: "тогда более чем честно",
    // "прям очень коротко"); keep it in step with forgetUser. The ID itself can't be encrypted, the bot writes to it.
    "<b>Что я храню и зачем.</b>\n" +
    "• Telegram ID без имени, ника и фото и служебное (дата запуска, какие уведомления ушли): чтобы отвечать и присылать уведомления.\n" +
    "• Отметки (и оценки на сайте): для списков, «Наверстать» и напоминаний. Убрать: нажми ещё раз, оценку — «—».\n" +
    "• «Понравилось»: для списка. Убрать: нажми ♥ ещё раз.\n" +
    "• Артисты: чтобы писать о новых альбомах. Убрать: «" + FOLLOWS_BUTTON + "».\n" +
    "• Место в «Наверстать»: чтобы продолжить с него.\n" +
    "• Голоса «Вайб для»: для вайба альбома.\n" +
    "Другим видны только средняя оценка и итог голосов по альбому, когда их хотя бы 3. Всё в зашифрованной базе Cloudflare, никому не передаётся. /forget удалит всё сразу, а голоса за вайб оставит без ID; из резервных копий данные уйдут за 90 дней.\n\n" +
    "Неофициальный проект. Не связан с Anthony Fantano и The Needle Drop.";
}

async function sendHelp(env, uid) {
  await setSetting(env, `menu:${uid}`, MENU_V);
  return tg(env, "sendMessage", { chat_id: uid, parse_mode: "HTML", link_preview_options: { is_disabled: true }, text: helpText(env), reply_markup: MENU });
}

// A keyboard sent before the menu changed stays until the bot sends a new one: once, with the person's next message.
async function maybeNewMenu(env, uid) {
  const user = await env.DB.prepare("SELECT 1 FROM users WHERE user_id=?").bind(uid).first();
  if (!user || (await getSetting(env, `menu:${uid}`)) === MENU_V) return;
  await setSetting(env, `menu:${uid}`, MENU_V);
  await tg(env, "sendMessage", { chat_id: uid, text: `В меню обновление: «Отложенные» теперь «${LATER_BUTTON}» и идут первыми в «${QUEUE_BUTTON}», а в «${LIKED_BUTTON}» собираются альбомы с отметкой «♡ Понравилось».`, reply_markup: MENU });
}

async function onCallback(q, env) {
  const uid = q.from.id;
  const parts = (q.data || "").split(":");
  let answer = "";
  let answered = false;
  // Telegram shows a spinner on the button until it's answered and drops answers that come too late, so the slow
  // follow-ups (lists, the similar albums, a card with Deezer lookups) run after the answer.
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
    if (next === "nope" && (await setLike(env, uid, rid, false))) {
      answer += ", и убрано из понравившегося";
      await showLike(env, q, rid, false);
    }
    await answerNow();
    if (isOwner(env, uid)) await refreshOwnerLists(env);
    else await dropDmPin(env, uid);
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
  } else if (parts[0] === "ma") {
    await answerNow();
    await askMood(env, uid, parts[1], true, q.message && q.message.message_id);
  } else if (parts[0] === "mq") {
    await answerNow();
    await askMood(env, uid, parts[1]);
  } else if (parts[0] === "dz") {
    await answerNow();
    await sendDeezerAlbum(env, uid, parts[1]);
  } else if (parts[0] === "ql") { // a page of «Дослушать»: ql:<from id>:<offset>
    await answerNow();
    await sendQueue(env, uid, { fromId: parts[1], offset: Number(parts[2]) || 0, confirmed: true, edit: q.message && q.message.message_id });
  } else if (parts[0] === "qa") { // «с другого альбома»
    await answerNow();
    await askQueueFrom(env, uid);
  } else if (parts[0] === "qf") { // picked the album to start after
    await answerNow();
    await env.DB.prepare("DELETE FROM settings WHERE key=?").bind(`qfrom:${uid}`).run();
    await sendQueue(env, uid, { fromId: parts[1], confirmed: true });
  } else if (parts[0] === "qo") { // a card from the list, with «→ дальше»
    await answerNow();
    await openQueueCard(env, uid, parts[1]);
  } else if (parts[0] === "lp") { // a page of «♥ Понравившееся»
    await answerNow();
    await sendLiked(env, uid, Number(parts[1]) || 0, q.message && q.message.message_id);
  } else if (parts[0] === "lk") { // «♡ Понравилось»: on and off; a separate mark that «Слушал» doesn't overwrite
    const on = !(await isLiked(env, uid, parts[1]));
    await setLike(env, uid, parts[1], on);
    const cur = await env.DB.prepare("SELECT status FROM marks WHERE user_id=? AND review_id=?").bind(uid, parts[1]).first();
    if (on && cur && cur.status === "nope") await setMark(env, uid, parts[1], "done", undefined); // liked isn't «не моё»
    answer = on ? `♥ В списке «${LIKED_BUTTON.slice(2)}»` : "Убрано из понравившегося";
    await answerNow();
    await showLike(env, q, parts[1], on);
  } else if (parts[0] === "qd" || parts[0] === "qs") {
    // «Наверстать»: marked (qd:<id>[:later|nope|done][:l]) or skipped (qs:<id>[:l]): this card goes, the next comes.
    // One album has one mark, so «Послушал → дальше» after «Отложить» used to replace «отложено» with «прослушано»
    // (the owner found «Отложенные» empty after a «Наверстать» session, 2026-11-02): here every mark moves on by itself.
    const st = parts[2] === "later" || parts[2] === "nope" ? parts[2] : "done";
    const section = (parts[0] === "qd" ? parts[3] : parts[2]) === "l" ? "l" : "c";
    // the block's next is found before the mark takes this one out of it
    const nextLater = section === "l" ? await laterNeighbour(env, uid, await archive(env), parts[1], 1) : null;
    if (parts[0] === "qd") {
      await setMark(env, uid, parts[1], st, undefined);
      answer = `Отмечено: ${STATUS_LABEL[st]}`;
      if (st === "nope" && (await setLike(env, uid, parts[1], false))) answer += ", и убрано из понравившегося";
    }
    // the place in «Наверстать» is the last card of the reviews' part acted on there, not the newest album marked
    // anywhere: a fresh album heard from the «Послушать потом» block or the channel doesn't skip the ones before it
    if (section === "c") await setSetting(env, `qpos:${uid}`, parts[1]);
    await answerNow();
    if (q.message) await tg(env, "deleteMessage", { chat_id: uid, message_id: q.message.message_id });
    await queueNext(env, uid, parts[1], section, nextLater);
    if (parts[0] === "qd") {
      if (isOwner(env, uid)) await refreshOwnerLists(env);
      else await dropDmPin(env, uid);
    }
  } else if (parts[0] === "qb") { // «← Назад»: this card goes, the review published before it comes
    await answerNow();
    const arch = await archive(env);
    const cur = arch.find((x) => x.id === parts[1]);
    const later = parts[2] === "l"; // in the «Послушать потом» block: the one before it there
    const prev = cur && (later ? await laterNeighbour(env, uid, arch, cur.id, -1) : before(arch, cur));
    if (!prev) {
      return tg(env, "sendMessage", { chat_id: uid,
        text: later ? "Это первый альбом в «Послушать потом»." : "Раньше этого обзора в архиве ничего нет." });
    }
    if (q.message) await tg(env, "deleteMessage", { chat_id: uid, message_id: q.message.message_id });
    await openQueueCard(env, uid, prev.id, later ? "l" : "c");
  } else if (parts[0] === "fg") { // /forget: fg:y deletes everything about this person, fg:n keeps it
    if (parts[1] === "y") await forgetUser(env, uid);
    answer = parts[1] === "y" ? "Удалено" : "Ничего не удалено";
    await answerNow();
    if (q.message) await tg(env, "deleteMessage", { chat_id: uid, message_id: q.message.message_id });
    await tg(env, "sendMessage", { chat_id: uid, ...(parts[1] === "y"
      ? { text: "Готово: я больше ничего о тебе не храню. Если захочешь вернуться, нажми /start.", reply_markup: { remove_keyboard: true } }
      : { text: "Хорошо, всё осталось как было." }) });
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
    // "другое": continue in the private chat, where the bot can show the options
    return tg(env, "answerCallbackQuery", { callback_query_id: q.id, url: `https://t.me/${env.BOT_USERNAME}?start=mood_${parts[1]}` });
  } else if (parts[0] === "vo") {
    const [, rid, mi] = parts;
    // an old message's button may carry a merged or retired word: merged count as the new one, retired aren't stored
    const mood = shownMoods([MOODS[Number(mi)]])[0];
    if (!mood) answer = "Этого варианта больше нет";
    else {
      await env.DB.prepare("INSERT INTO mood_votes (user_id, review_id, mood, vote) VALUES (?,?,?, 'y') ON CONFLICT(user_id, review_id, mood) DO UPDATE SET vote='y'").bind(uid, rid, mood).run();
      answer = `Записал: вайб для ${vibe(mood)}`;
    }
  } else if (parts[0] === "v" || parts[0] === "w") {
    // w:<id>:<MOODS index>:y|n — a vote on a card's guess; MOODS only grows, so the index means one word for good.
    // v:<id>:<i>:y|n — the same on cards sent before 2026-11-02: i counts in that card's list as it was then; a word
    // merged since counts as the new one, a retired one isn't stored (no vote under the wrong word).
    const [, rid, idx, vote] = parts;
    let word = MOODS[Number(idx)];
    if (parts[0] === "v") {
      const r = (await reviews(env)).find((x) => x.id === rid);
      word = cardMoods(r, r && r.ai && r.ai.moods && r.ai.moods.length ? null : await criticsOf(env, rid), true)[Number(idx)];
    }
    const mood = word ? shownMoods([word])[0] || null : null;
    if (word && !mood) answer = "Этого варианта больше нет";
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
  if (st === null && sc === null) { // nothing left to keep: «Отметка снята» means the row is gone, not emptied
    await env.DB.prepare("DELETE FROM marks WHERE user_id=? AND review_id=?").bind(uid, rid).run();
    return;
  }
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

// «♡ Понравилось» (owner, 2026-11-02): its own table, so no status (heard, later, not mine) overwrites it
async function isLiked(env, uid, rid) {
  return !!(rid && (await env.DB.prepare("SELECT 1 FROM likes WHERE user_id=? AND review_id=?").bind(uid, rid).first()));
}

// -> true when it changed
async function setLike(env, uid, rid, on) {
  const r = on
    ? await env.DB.prepare("INSERT OR IGNORE INTO likes (user_id, review_id, liked_at) VALUES (?,?,?)").bind(uid, rid, now()).run()
    : await env.DB.prepare("DELETE FROM likes WHERE user_id=? AND review_id=?").bind(uid, rid).run();
  return !!(r && r.meta && r.meta.changes);
}

// ♡ / ♥ on the pressed card. Only in the private chat: a channel post's buttons are the same for everyone.
async function showLike(env, q, rid, on) {
  const m = q.message;
  if (!m || !m.chat || m.chat.type !== "private" || !m.reply_markup) return;
  const kb = m.reply_markup.inline_keyboard.map((row) => row.map((b) => (b.callback_data === `lk:${rid}` ? likeButton(rid, on) : b)));
  await tg(env, "editMessageReplyMarkup", { chat_id: m.chat.id, message_id: m.message_id, reply_markup: { inline_keyboard: kb } });
}

function statusMap(marks) {
  const out = {};
  for (const [k, v] of Object.entries(marks)) if (v.status) out[k] = v.status;
  return out;
}

// Open to anyone (the site's album pages), so it never gives exact numbers (owner, 2026-11-02): an album shows up
// only once at least PUBLIC_MIN people scored or voted, so no single person's score can be read off it, and the size
// is only "fewer than 10" or "10 or more" (many).
const PUBLIC_MIN = 3;
const PUBLIC_MANY = 10;

async function publicStats(env) {
  const avg = {};
  const { results } = await env.DB.prepare(
    "SELECT review_id, AVG(score) AS avg, COUNT(score) AS n FROM marks WHERE score IS NOT NULL GROUP BY review_id HAVING COUNT(score) >= ?"
  ).bind(PUBLIC_MIN).all();
  for (const r of results) avg[r.review_id] = { avg: Math.round(r.avg * 10) / 10, many: r.n >= PUBLIC_MANY };
  const people = {};
  const p = await env.DB.prepare("SELECT review_id, COUNT(DISTINCT user_id) AS n FROM mood_votes GROUP BY review_id HAVING COUNT(DISTINCT user_id) >= ?")
    .bind(PUBLIC_MIN).all();
  for (const r of p.results) people[r.review_id] = r.n;
  const sums = {};
  const v = await env.DB.prepare("SELECT review_id, mood, SUM(vote='y') AS y, SUM(vote='n') AS n FROM mood_votes GROUP BY review_id, mood").all();
  for (const r of v.results) {
    if (!people[r.review_id]) continue;
    const m = MOOD_ALIAS[r.mood] || r.mood;
    if (!VIBES[m]) continue; // retired
    const x = ((sums[r.review_id] ||= {})[m] ||= { y: 0, n: 0 });
    x.y += Number(r.y) || 0;
    x.n += Number(r.n) || 0;
  }
  const moods = {};
  for (const [rid, ms] of Object.entries(sums)) {
    const top = Math.max(1, ...Object.values(ms).map((x) => x.y));
    // per vibe: settled by a majority or not, and the bar's length rounded to a tenth; no counts
    const list = Object.entries(ms).filter(([, x]) => x.y || x.n)
      .map(([m, x]) => ({ m, ok: x.y > x.n, bar: Math.round((10 * x.y) / top) * 10 }))
      .sort((a, b) => b.ok - a.ok || b.bar - a.bar || a.m.localeCompare(b.m));
    if (list.length) moods[rid] = { many: people[rid] >= PUBLIC_MANY, list };
  }
  return { avg, moods };
}

// ---------- pinned lists ----------

async function openCard(env, uid, open) {
  const [kind, id] = [open.slice(0, open.indexOf(":")), open.slice(open.indexOf(":") + 1)];
  if (kind === "dz") return sendDeezerAlbum(env, uid, id);
  if (kind === "mb") return sendMbAlbum(env, uid, id, null);
  if (kind === "q") return openQueueCard(env, uid, id);
  const a = (await archive(env)).find((x) => x.id === id) || (await reviews(env)).find((x) => x.id === id);
  if (a) return sendAlbum(env, uid, a, "");
  return tg(env, "sendMessage", { chat_id: uid, text: "Не нашёл этот альбом." });
}

// The bot's data files (data/*.json) live in a private GitHub repo since 2026-11-03 (the datasets are not to be
// downloadable in one click; the code stays public). DATA_URL is that repo's raw address of reviews.json, and the
// DATA_TOKEN secret (a read-only GitHub token) opens it. Without the token: a public address, as before.
function dataFile(env, name, cacheTtl) {
  const url = name === "reviews.json" ? env.DATA_URL : env.DATA_URL.replace("reviews.json", name);
  const headers = env.DATA_TOKEN ? { Authorization: `token ${env.DATA_TOKEN}`, "User-Agent": "laziest-music-nerd" } : undefined;
  return fetch(url, { headers, cf: { cacheTtl } });
}

async function listItems(env) {
  // GitHub Actions pushes the fresh list here after each new review; the repo copy is only a fallback.
  const cached = await getSetting(env, "list_items");
  if (cached) return JSON.parse(cached);
  const r = await dataFile(env, "list.json", 120);
  return r.ok ? (await r.json()).items : [];
}

async function reviews(env) {
  const r = await dataFile(env, "reviews.json", 300);
  return r.ok ? r.json() : [];
}

// Length as Telegram counts it for the 4096 limit: visible text after HTML parsing (tags and link URLs don't count),
// in UTF-16 units, which is what a JS string's length already is.
function tgLen(html) {
  return html.replace(/<[^>]+>/g, "").replace(/&(?:[a-z]+|#\d+);/gi, "x").length;
}

// Above the channel's pinned list: a short welcome and how the channel and the bot work (lmn/card.py pin_intro)
function pinIntro(env) {
  const bot = env.BOT_USERNAME;
  return "<b>Привет!</b> Здесь мы знакомимся с новой музыкой, отталкиваясь от обзоров Anthony Fantano.\n\n" +
    "<b>Канал:</b> карточка каждого нового обзора с оценкой, описанием, критиками, треклистом и ссылками, где послушать.\n" +
    `<b>Бот</b> <a href="https://t.me/${bot}">@${bot}</a>: поиск любого альбома из архива, ` +
    "«Наверстать» пропущенные обзоры, списки «Послушать потом» и «Понравившееся», сообщения о новых альбомах артистов, за которыми следишь.\n" +
    "Кнопки под постами: «✓ Слушал»; «♡ Понравилось» — отдельный список, «Слушал» его не стирает; «⏳ Послушать потом» — эти альбомы идут первыми в «Наверстать»; «✗ Не моё». Кнопки видят все, а твои отметки только ты.\n" +
    "Ниже 30 последних обзоров: нажми на альбом, и бот пришлёт его карточку.\n\n" +
    "<i>Неофициальный проект, не связан с Anthony Fantano и The Needle Drop.</i>\n\n";
}

function renderList(env, items, statuses) {
  const tail = `\n\n<a href="https://t.me/${env.BOT_USERNAME}">Бот</a>: поиск по архиву, «Наверстать», понравившееся` +
    (env.SITE_LIVE === "1" ? ` · <a href="${env.SITE_URL}/">сайт</a>` : ""); // the same in lmn/card.py list_tail
  const head = pinIntro(env) + LIST_HEAD;
  let lines = items.map((i) => i.line + (STATUS_ICON[statuses[i.id]] || ""));
  while (lines.length && tgLen(head + lines.join("\n") + tail) > MESSAGE_LIMIT) lines.pop();
  return head + (lines.length ? lines.join("\n") : "Пока пусто.") + tail;
}

// Since 2026-11-02 there is no pinned list in a private chat (the owner: «пусть появляется по нажатию кнопки список
// отложенных просто»): the «⏳ Послушать потом» button shows it. A pinned list left from before is unpinned and deleted the
// next time this person marks something (or by the daily cron, migrateDmPins).
async function dropDmPin(env, uid) {
  const user = await env.DB.prepare("SELECT dm_pinned_id FROM users WHERE user_id=?").bind(uid).first();
  if (!user || !user.dm_pinned_id) return;
  await tg(env, "unpinChatMessage", { chat_id: uid, message_id: user.dm_pinned_id });
  await tg(env, "deleteMessage", { chat_id: uid, message_id: user.dm_pinned_id });
  await env.DB.prepare("UPDATE users SET dm_pinned_id=NULL WHERE user_id=?").bind(uid).run();
}

// /forget: asked once with a button, so a stray tap on the command deletes nothing
async function askForget(env, uid) {
  return tg(env, "sendMessage", { chat_id: uid,
    text: "Удалить всё, что я о тебе храню? Это твой Telegram ID, отметки и оценки, «Понравилось», артисты, за которыми ты следишь, и место в «Наверстать». Голоса «Вайб для» останутся, но без ID. Вернуть это будет нельзя.",
    reply_markup: { inline_keyboard: [[{ text: "Да, удалить всё", callback_data: "fg:y" }, { text: "Отмена", callback_data: "fg:n" }]] } });
}

// Every row about one person. A table with a user_id column that is added later must be added here too
// (worker/test/forget.test.mjs checks schema.sql for that).
const USER_TABLES = ["marks", "likes", "follows", "follow_sent", "users"];
// Kept without the person (the owner, 2026-11-02): their votes move to a random negative ID that no Telegram account
// has, one per forgotten person, so an album's "at least 3 people" still counts them once.
const ANON_TABLES = ["mood_votes"];
const USER_SETTINGS = ["menu", "qpos", "qfrom"];
async function forgetUser(env, uid) {
  await dropDmPin(env, uid); // a pinned list left in the chat, while users still knows its message
  const anon = -(Math.floor(Math.random() * 2 ** 50) + 1);
  await env.DB.batch([
    ...ANON_TABLES.map((t) => env.DB.prepare(`UPDATE ${t} SET user_id=? WHERE user_id=?`).bind(anon, uid)),
    ...USER_TABLES.map((t) => env.DB.prepare(`DELETE FROM ${t} WHERE user_id=?`).bind(uid)),
    ...USER_SETTINGS.map((k) => env.DB.prepare("DELETE FROM settings WHERE key=?").bind(`${k}:${uid}`)),
  ]);
  if (isOwner(env, uid)) await refreshOwnerLists(env); // the owner's marks also leave the channel's pinned list
}

async function refreshOwnerLists(env) {
  const uid = Number(env.OWNER_ID);
  await dropDmPin(env, uid);
  if ((await getSetting(env, "show_in_channel")) === "0") return;
  const st = await dataFile(env, "state.json", 120);
  const pinned = st.ok ? (await st.json()).channel_pinned_id : null;
  if (!pinned) return;
  const text = renderList(env, await listItems(env), statusMap(await userMarks(env, uid)));
  await tg(env, "editMessageText", { chat_id: env.CHANNEL, message_id: pinned, text, parse_mode: "HTML", link_preview_options: { is_disabled: true } });
}

// ---------- archive: random pick, similar albums, mood "другое" ----------

let archiveCache = null; // kept while this Worker instance lives, so a search doesn't parse 1.4 MB every time

async function archive(env) {
  if (archiveCache && Date.now() - archiveCache.at < 600e3) return archiveCache.data;
  const r = await dataFile(env, "archive.json", 3600);
  if (!r.ok) return archiveCache ? archiveCache.data : [];
  archiveCache = { at: Date.now(), data: await r.json() };
  return archiveCache.data;
}

const good = (a) => !a.guest && (a.classic || (a.score != null && a.score >= 8)) && a.artist_name && a.album;
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

// Our own site's page for the album, a line under the links, worded so it can't be taken for the artist's or the
// album's site (owner, 2026-11-02). Empty while the site is off.
function siteLine(env, r) {
  return env.SITE_URL && env.SITE_LIVE === "1" && r.id
    ? `\n\n<a href="${env.SITE_URL}/r/${encodeURIComponent(r.id)}.html">Этот альбом на нашем сайте</a>` : ""; // apart from the links: it read as one of them
}

// The album in Deezer's search. Plain words first: Deezer's field search (artist:"…" album:"…") answers nothing for
// many albums it has (checked from Actions 2026-11-02: Taylor Swift "The Life of a Showgirl", Angine de Poitrine "Vol.
// II", Ghost "Skeletá"), so it is only the second try. Fantano's "Self-Titled" is the artist's name there; a review of
// "Nas & DJ Premier" is an album of "Nas" there, so any credited name counts, the full one first.
async function deezerHit(artist, album) {
  const want = selfTitled(artist, album);
  const names = creditedNames(artist);
  for (const q of [`${artist} ${want}`, `artist:"${names[names.length > 1 ? 1 : 0]}" album:"${want}"`]) {
    const r = await fetch(`https://api.deezer.com/search/album?q=${encodeURIComponent(q)}&limit=25`);
    const hit = pickAlbum(r.ok ? (await r.json()).data : [], names, want);
    if (hit) return hit;
  }
  return null;
}

// The Deezer album, checked against the names (deezer.mjs pickAlbum): cover, track count, length and the tracklist.
async function deezerAlbum(artist, album) {
  try {
    const hit = await deezerHit(artist, album);
    if (!hit) return null;
    const full = await fetch(`https://api.deezer.com/album/${hit.id}`).then((x) => (x.ok ? x.json() : {})).catch(() => ({}));
    const list = ((full.tracks && full.tracks.data) || []).map((t) => ({ title: t.title, sec: t.duration || null }));
    return { id: hit.id, artistId: hit.artist.id || null, cover: hit.cover_xl || hit.cover_big || null, link: hit.link, tracks: hit.nb_tracks || null, list,
             minutes: full.duration ? Math.round(full.duration / 60) : null,
             genres: ((full.genres && full.genres.data) || []).map((g) => g.name),
             year: /^\d{4}/.test(full.release_date || "") ? full.release_date.slice(0, 4) : null };
  } catch (e) {
    return null;
  }
}


// The album's page on Apple Music, from Apple's public iTunes Search API (no key; made for linking to the store).
// Only an exact match of artist and title counts; otherwise null and the card gets a search link instead.
async function appleAlbum(artist, album) {
  try {
    const r = await appleSearch(`${artist} ${untitled(album)}`);
    if (!r.ok) console.log("itunes search", r.status);
    const d = r.ok ? await r.json() : {};
    const want = nameKey(untitled(album));
    // Apple names a single "Title - Single" and an EP "Title - EP": a single of the same name is not the album
    const hit = (d.results || []).find((x) => nameKey(x.artistName) === nameKey(artist) && !/ - Single$/.test(x.collectionName || "") &&
      nameKey(untitled(String(x.collectionName || "").replace(/ - EP$/, ""))) === want);
    return hit && hit.collectionViewUrl ? hit.collectionViewUrl.split("?")[0] : null;
  } catch (e) {
    return null;
  }
}

function appleSearch(term) {
  return fetch(`https://itunes.apple.com/search?term=${encodeURIComponent(term)}&entity=album&limit=10`, {
    headers: { "User-Agent": UA, Accept: "application/json" },
    cf: { cacheTtlByStatus: { "200-299": 86400, "400-599": 0 } }, // a refusal (rate limit) isn't kept for a day
  });
}

// The streaming links of a card (owner, 2026-11-02): YouTube Music, Apple Music (when the album is found), SoundCloud, then Bandcamp, or
// Google's search when no Bandcamp page is known. SoundCloud has no open API, so it is always its search.
function listenLinks(q, ytm, apple, bandcamp) {
  return [
    ytm ? ["YouTube Music", ytm] : ["искать в YouTube Music", `https://music.youtube.com/search?q=${q}`],
    // only the album itself: Music on a Mac opens a search link but drops the query (owner, 2026-11-02)
    ...(apple ? [["Apple Music", apple]] : []),
    ["искать в SoundCloud", `https://soundcloud.com/search?q=${q}`],
    bandcamp || ["искать в Google", `https://www.google.com/search?q=${q}`],
  ];
}

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
  const reviewed = reviewedIn(arch, x.artist, x.title);
  if (reviewed) return sendAlbum(env, uid, reviewed, "");
  return sendCard(env, uid, await unreviewedCard(env, { ...x, liked: await isLiked(env, uid, x.key) }, arch));
}

// Fantano's review of this album, if there is one
function reviewedIn(list, artist, title) {
  const k = nameKey(artist);
  const t = nameKey(untitled(title));
  return t ? list.find((a) => nameKey(a.artist_name) === k && nameKey(untitled(a.album)) === t) : null;
}

// «Наверстать» cards (opened from that list): each mark takes this card away and brings the next one. «✓ Слушал» isn't
// repeated there, «Послушал → дальше» marks it (owner, 2026-11-02). «⏳ Потом» and «Не моё» move on too, so no second
// press can overwrite them. section "l": a card from the «Послушать потом» block at the top (no «Потом» there; the
// callbacks end in ":l", so «дальше» and «Назад» stay in that block), "c": the reviews after the person's place.
function queueRows(id, liked, section) {
  const l = section === "l" ? ":l" : "";
  const heard = { text: "✓ Послушал → дальше", callback_data: l ? `qd:${id}:done:l` : `qd:${id}` };
  const nope = { text: "✗ Не моё → дальше", callback_data: `qd:${id}:nope${l}` };
  const skip = { text: "Пропустить →", callback_data: `qs:${id}${l}` };
  const back = { text: "← Назад", callback_data: `qb:${id}${l}` };
  return l ? [[likeButton(id, liked), heard], [nope, skip], [back]]
    : [[likeButton(id, liked), heard], [{ text: "⏳ Потом → дальше", callback_data: `qd:${id}:later` }, nope], [back, skip]];
}

// A card that went out as a photo when it could, else as text.
async function sendCard(env, uid, { text, reply_markup, cover }) {
  if (cover) {
    const r = await tg(env, "sendPhoto", { chat_id: uid, photo: cover, caption: text, parse_mode: "HTML", reply_markup });
    if (r.ok) return r;
  }
  return tg(env, "sendMessage", { chat_id: uid, text, parse_mode: "HTML", reply_markup, link_preview_options: { is_disabled: true } });
}

// The card of an album without Fantano's review. x.fresh: the release date of a just-released album (watchReleases).
async function unreviewedCard(env, x, arch) {
  const k = nameKey(x.artist);
  const [rt, apple] = await Promise.all([wikiCritics(x.artist, untitled(x.title)), appleAlbum(x.artist, x.title)]);
  const facts = [
    (x.genres || []).slice(0, 3).join(", "),
    x.kind,
    x.tracks ? tracksWord(x.tracks) : "",
    x.minutes ? `${x.minutes} мин` : "",
  ].filter(Boolean).join(" · ");
  // a just-released album: "no reviews yet" only while Wikipedia has no critics either (the owner: not Fantano-centric)
  const status = x.fresh ? `🆕 Вышел ${ruDate(x.fresh)}${criticsText(rt) ? "" : ", обзоров пока нет"}` : "⚪ Фантано не обозревал";
  const head = (x.intro ? x.intro + "\n\n" : "") +
    `<b>${esc(x.artist)} — ${esc(x.title)}</b>${x.year ? ` (${x.year})` : ""}\n${status}${facts ? " · " + esc(facts) : ""}${criticsText(rt) ? "\n" + criticsText(rt) : ""}`;
  const q = encodeURIComponent(`${x.artist} ${x.title}`);
  const known = arch.find((a) => nameKey(a.artist_name) === k); // any review of the artist: follow and their list work through it
  const text = head + "\n\n" + linkItems([
    ...listenLinks(q, null, apple, bandcampLink({}, x.artist, x.title)),
    ["оценки на AOTY", `https://www.albumoftheyear.org/search/?q=${q}`],
  ]);
  const rows = []; // only actions: the links are in the text
  if (x.key) {
    // remembered so that "⏳ Послушать потом", "♥ Понравившееся", the reminder and "▶ Отрывки" know what this ID is
    await env.DB.prepare("INSERT INTO unreviewed (id, artist_name, album, year) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET artist_name=excluded.artist_name, album=excluded.album, year=excluded.year")
      .bind(x.key, x.artist, x.title, x.year || null).run();
    rows.push(...MARK_ROWS(x.key, !!x.liked)); // x.liked: this person liked it (sendUnreviewed)
  }
  if (known) rows.push([{ text: "🔔 Следить", callback_data: `f:${known.id}` }, { text: "📚 Все обзоры", callback_data: `ar:${known.id}` }]);
  return { text, reply_markup: { inline_keyboard: rows }, cover: x.cover };
}

// The card's links as one line of text (owner, 2026-11-02: buttons in the bot only for actions). A search stands in
// where the address isn't known and says so ("искать …"). Album of the Year: a link to its search only, nothing is
// fetched from AOTY. Bandcamp: the album's page when lmn/bandcamp.py or Fantano's "Listen:" (rt.bc) found it, the
// artist's page labelled as such, else nothing (listenLinks puts Google's search there); there is no Bandcamp API.
function bandcampLink(links, artist, album, fromVideo) {
  const bc = links && links.bandcamp;
  const label = (u) => (/^https?:\/\/[a-z0-9-]+\.bandcamp\.com\/?$/i.test(u) ? "Bandcamp артиста" : "Bandcamp");
  if (bc && !bc.includes("bandcamp.com/search")) return [label(bc), bc];
  if (fromVideo && /^https:\/\/([a-z0-9-]+\.)?bandcamp\.com\//i.test(fromVideo)) return [label(fromVideo), fromVideo];
  return null; // no page known: the card offers Google's search instead (owner, 2026-11-02)
}

function linkItems(items) {
  return "<b>Ссылки:</b> " + items.map(([t, u]) => `<a href="${esc(u).replace(/"/g, "&quot;")}">${esc(t)}</a>`).join(" · ");
}

// A full card for one review, as in the channel: cover, score, genres, length, links, marks and "🔔".
// a: an archive entry; a review the bot posted a card for has more in reviews.json, and that is used first.
async function sendAlbum(env, uid, a, intro, opts = {}) {
  const full = (await reviews(env)).find((x) => x.id === a.id);
  const r = full || a;
  const links = (full && full.links) || {};
  const [dz, rt] = await Promise.all([
    (full && full.covers && full.covers.length && full.duration_min) ? null : deezerAlbum(r.artist_name, r.album),
    criticsOf(env, r.id),
  ]);
  // a card the bot posted has it (lmn/links.py), an archive album from Actions (lmn/apple.py, in rt); the live search
  // last: Apple often refuses the Worker (429, its address is shared with other Cloudflare sites)
  const apple = links.apple || (rt && rt.apple) || await appleAlbum(r.artist_name, r.album);
  const cover = (full && full.covers && full.covers[0]) || (dz && dz.cover);
  const tracks = (full && full.tracks && full.tracks.length) || (dz && dz.tracks);
  const list = (full && full.tracks && full.tracks.length ? full.tracks : dz && dz.list) || [];
  const minutes = (full && full.duration_min) || (dz && dz.minutes);
  // The release year; Deezer may only have a later reissue, so its year counts only if it isn't after the review.
  const reviewYear = String(r.published).slice(0, 4);
  const ofArtist = (await archive(env)).filter((x) => nameKey(x.artist_name) === nameKey(r.artist_name))
    .sort((x, y) => String(x.published).localeCompare(String(y.published)));
  const nth = ofArtist.findIndex((x) => x.id === r.id) + 1;
  const year = (full && full.year) || (dz && dz.year && dz.year <= reviewYear ? dz.year : null);
  const facts = [
    genresOf(r).slice(0, 3).join(", "),
    tracks ? tracksWord(tracks) : "",
    minutes ? `${minutes} мин` : "",
    year ? "" : `обзор ${reviewYear}`, // the review year only when the release year is unknown
    r.guest ? "гостевой обзор" : "",
    nth && ofArtist.length > 1 ? `${nth}-й из ${ofArtist.length} обзоров артиста` : "",
  ].filter(Boolean).join(" · ");
  // the short brief: the card's own (Gemini), else the archive's (lmn/briefs.py, in rt); Fantano's line only without one
  const brief = (full && full.ai && full.ai.brief) || (rt && rt.brief);
  const moods = cardMoods(full, rt);
  const fav = (full && full.ai && full.ai.best_tracks && full.ai.best_tracks.length ? full.ai.best_tracks : rt && rt.fav) || [];
  // Paragraphs (owner, 2026-11-01: one block read as glued): the title and score; Fantano's words; the critics;
  // when to listen; the tracklist folded, as in the channel's card.
  const about = [
    brief ? `<b>Описание:</b> ${esc(brief)}` : "",
    rt && rt.blurb && !brief ? `💬 <i>${esc(rt.blurb)}</i>` : "",
    fav.length && !list.length ? `★ Любимые у Фантано: ${esc(fav.join(", "))}` : "", // with a tracklist, ★ marks them there
  ].filter(Boolean).join("\n");
  const head = (intro ? intro + "\n\n" : "") + `<b>${esc(r.artist_name)} — ${esc(r.album)}</b>${year ? ` (${year})` : ""}\n${badge(r)}${facts ? " · " + esc(facts) : ""}`;
  const q = encodeURIComponent(`${r.artist_name} ${r.album}`);
  const vid = r.video_id || (rt && rt.video_id); // most archive reviews have it only in rt (lmn/notes.py: the video's page)
  const linkLine = linkItems([
    vid ? ["Видеообзор", `https://youtu.be/${vid}`] : ["Обзор", r.url],
    // no «Все платформы» (album.link) in the bot: the owner didn't like how it reads or what it opens (2026-11-02); the site keeps it
    ...listenLinks(q, links.youtube_album, apple, bandcampLink(links, r.artist_name, r.album, rt && rt.bc)),
    ["оценки на AOTY", `https://www.albumoftheyear.org/search/?q=${q}`],
    // no «любимые треки на сайте» (owner, 2026-11-02: services instead); the site keeps the player
  ]) + siteLine(env, r);
  const paras = [head, about, criticsText(rt).trim(),
    moods.length ? `<b>Вайб для:</b> ${esc(moods.map(vibe).join(" / "))} <i>(догадка ИИ, поправь кнопками)</i>` : ""];
  const base = paras.filter(Boolean).join("\n\n");
  // a photo's caption takes 1024 characters: when even the text without a tracklist is longer, the card is a message
  // (4096, the whole tracklist) with the cover as its link preview above the text
  const asPhoto = cover && tgLen(base + "\n\n" + linkLine) <= CAPTION_LIMIT;
  const text = withTracklist(base, list, fav, asPhoto ? CAPTION_LIMIT : MESSAGE_LIMIT, linkLine);
  // only actions (owner, 2026-11-02); the links are the text's last line
  const liked = await isLiked(env, uid, r.id);
  const reply_markup = { inline_keyboard: [
    ...(opts.queue ? queueRows(r.id, liked, opts.queue) : MARK_ROWS(r.id, liked)),
    [{ text: "🔔 Следить", callback_data: `f:${r.id}` }, { text: "📚 Все обзоры", callback_data: `ar:${r.id}` }],
    // the AI's mood guess gets the channel card's vote (да / нет, «другое» asks all four); without one, a button asks
    ...moods.map((m) => [{ text: `для ${vibe(m)}: да`, callback_data: `w:${r.id}:${MOODS.indexOf(m)}:y` }, { text: "нет", callback_data: `w:${r.id}:${MOODS.indexOf(m)}:n` }]),
    [{ text: moods.length ? "Вайб: другое" : "✨ Вайб для чего?", callback_data: `mq:${r.id}` }],
  ] };
  if (asPhoto) {
    const d = await tg(env, "sendPhoto", { chat_id: uid, photo: cover, caption: text, parse_mode: "HTML", reply_markup });
    if (d.ok) return d;
  }
  const preview = cover ? { url: cover, prefer_large_media: true, show_above_text: true } : { is_disabled: true };
  return tg(env, "sendMessage", { chat_id: uid, text: asPhoto ? withTracklist(base, list, fav, MESSAGE_LIMIT, linkLine) : text,
    parse_mode: "HTML", reply_markup, link_preview_options: preview });
}

// The card's text with the tracklist folded at the end (an expandable quote, as in the channel's card), ★ on Fantano's
// favourites. Lines go from the end while it is too long for the message; then the whole tracklist.
function withTracklist(text, list, fav, limit, tail = "") {
  // the links, under the tracklist (owner, 2026-11-02). The quote stands out by itself, so no blank lines around it
  // (owner, 2026-11-02); without a tracklist the links are a paragraph of their own
  const end = tail ? "\n\n" + tail : "";
  if (!list.length) return text + end;
  const best = fav.map(nameKey).filter(Boolean);
  const lines = list.map((t, i) => {
    const n = nameKey(t.title);
    const star = n && best.some((b) => b === n || (b.length > 3 && n.includes(b))) ? " ★" : "";
    const dur = t.sec ? ` ${Math.floor(t.sec / 60)}:${String(t.sec % 60).padStart(2, "0")}` : "";
    return `${i + 1}. ${esc(t.title)}${dur}${star}`;
  });
  const legend = lines.some((l) => l.endsWith("★")) ? " (★ — любимые у Фантано)" : "";
  for (let k = lines.length; k > 0; k--) {
    const shown = lines.slice(0, k).concat(k < lines.length ? [`… ещё ${lines.length - k}`] : []);
    const out = `${text}\n<blockquote expandable><b>Треклист</b>${legend}\n${shown.join("\n")}</blockquote>${tail ? "\n" + tail : ""}`;
    if (tgLen(out) <= limit) return out;
  }
  return text + end;
}

// ---------- «Наверстать» (was «Дослушать») ----------

// The person's place in «Наверстать»: the review after which the list goes on. Remembered (qpos) from the last card of
// the reviews' part acted on there or the album picked with «📍 С другого альбома»; until then the review published last
// among the ones marked heard. Kept because a fresh album heard from the «Послушать потом» block or the channel would
// otherwise move the start past everything before it. keep: remember a guessed start now (a card of the block is
// about to be marked heard); only showing the list doesn't, so an old guess not yet confirmed is asked about again.
async function queuePlace(env, uid, arch, statuses, keep = false) {
  const pos = await getSetting(env, `qpos:${uid}`);
  const known = pos && arch.find((a) => a.id === pos);
  if (known) return known;
  const from = lastHeard(arch, statuses);
  if (from && keep) await setSetting(env, `qpos:${uid}`, from.id);
  return from;
}

// The person's «Послушать потом» in the order of the «Наверстать» block (owner, 2026-11-02: «самые старые отложенные
// первыми, самые свеже отложенные последние»), and of the menu list («да в списке такой же порядок»).
async function laterIds(env, uid) {
  const { results } = await env.DB.prepare("SELECT review_id FROM marks WHERE user_id=? AND status='later' ORDER BY later_at, rowid").bind(uid).all();
  return results.map((r) => r.review_id);
}

// The review next to this one in the «Послушать потом» block (step +1 or -1), taken before the card's mark takes it out
// of the block. A card no longer in the block (marked elsewhere) goes on to the block's first, or back to its last.
async function laterNeighbour(env, uid, arch, id, step) {
  const block = laterReviews(arch, await laterIds(env, uid));
  const i = block.findIndex((a) => a.id === id);
  if (i < 0) return (step > 0 ? block[0] : block[block.length - 1]) || null;
  return block[i + step] || null;
}

const LATER_SHOWN = 10; // the «Послушать потом» block's lines in the list; the whole list is behind LATER_BUTTON

// «Наверстать»: the «Послушать потом» block on top (owner, 2026-11-02), then the reviews after the person's place, a
// page at a time. Without a place it asks which album to start after; a place older than OLD_DAYS is confirmed first.
async function sendQueue(env, uid, { fromId, offset = 0, confirmed = false, edit }) {
  const arch = await archive(env);
  const statuses = statusMap(await userMarks(env, uid));
  const picked = fromId && arch.find((a) => a.id === fromId);
  if (picked) await setSetting(env, `qpos:${uid}`, picked.id);
  const pos = !picked && (await getSetting(env, `qpos:${uid}`));
  const remembered = !!pos && arch.some((a) => a.id === pos); // a place reached in «Наверстать» before
  const from = picked || (await queuePlace(env, uid, arch, statuses));
  const later = offset ? [] : laterReviews(arch, await laterIds(env, uid));
  if (!from && !later.length) return askQueueFrom(env, uid, true);
  const send = (text, inline_keyboard) => tg(env, edit ? "editMessageText" : "sendMessage",
    { chat_id: uid, ...(edit ? { message_id: edit } : {}), text, parse_mode: "HTML", link_preview_options: { is_disabled: true }, reply_markup: { inline_keyboard } });
  const rest = from ? after(arch, from) : [];
  const name = from && `${esc(from.artist_name)} — ${esc(from.album)}`;
  const date = from && String(from.published).slice(0, 10).split("-").reverse().join(".");
  // only a start guessed from the marks is confirmed: a place the person reached in «Наверстать» is theirs already
  if (from && rest.length && !later.length && !confirmed && !fromId && !remembered && daysOld(from) > OLD_DAYS) {
    return send(`Последний прослушанный у тебя — <b>${name}</b>, обзор от ${date}. После него ${reviewsWord(rest.length)}: ` +
      `это больше года. Показать их, по ${PAGE} за раз?`,
      [[{ text: "Да, показать", callback_data: `ql:${from.id}:0` }], [{ text: "📍 С другого альбома", callback_data: "qa" }]]);
  }
  const line = (a) => queueLine(a, startLink(env, `q:${a.id}`), esc, STATUS_ICON[statuses[a.id]] || "");
  const parts = [];
  if (later.length) {
    const more = later.length - LATER_SHOWN;
    parts.push(`<b>${LATER_BUTTON}</b> · ${later.length}\n\n` + later.slice(0, LATER_SHOWN).map((a) => queueLine(a, startLink(env, `q:${a.id}`), esc, "")).join("\n") +
      (more > 0 ? `\n…и ещё ${more}: весь список — кнопка «${LATER_BUTTON}»` : ""));
  }
  const page = rest.slice(offset, offset + PAGE);
  if (!from) parts.push("Чтобы после них шли новые обзоры, нажми «📍 С какого альбома» и выбери, после какого начать.");
  else if (!rest.length) parts.push(`После <b>${name}</b> новых обзоров нет: ты нагнал(а) всё до последнего. 🏆`);
  else parts.push(`<b>${later.length ? "Новые обзоры" : "Наверстать"}</b> после ${name} (${date})\n` +
    `${reviewsWord(rest.length)}, здесь ${offset + 1}–${offset + page.length}\n\n${page.map(line).join("\n")}`);
  const first = later[0] || page[0];
  if (first) parts.push("Нажми на альбом: пришлю карточку. «Послушал → дальше» под ней отметит его и пришлёт следующий" +
    (later.length ? ", сначала из «Послушать потом»." : "."));
  const nav = first ? [{ text: "▶ С первого", callback_data: `qo:${first.id}` }] : [];
  if (from && offset + PAGE < rest.length) nav.push({ text: "Дальше ▸", callback_data: `ql:${from.id}:${offset + PAGE}` });
  return send((later.length ? "<b>Наверстать</b>\n\n" : "") + parts.join("\n\n"),
    [...(nav.length ? [nav] : []), [{ text: from ? "📍 С другого альбома" : "📍 С какого альбома", callback_data: "qa" }]]);
}

async function askQueueFrom(env, uid, noMarks = false) {
  await setSetting(env, `qfrom:${uid}`, now());
  return tg(env, "sendMessage", { chat_id: uid, text: (noMarks ? "Отметок «Слушал» у тебя пока нет. " : "") +
    "После какого альбома начать? Напиши его название или артиста: пришлю обзоры, вышедшие после него." });
}

// The answer to «после какого альбома?»: one hit starts the list, several are offered as buttons. The question is
// answered once: a text that names no review, or one sent more than QFROM_MINUTES later, is an ordinary search, so a
// question left open never takes over the search. Returns true when the text was taken as the answer.
async function queueFrom(env, uid, text) {
  const asked = await getSetting(env, `qfrom:${uid}`);
  if (!asked) return false;
  await env.DB.prepare("DELETE FROM settings WHERE key=?").bind(`qfrom:${uid}`).run();
  if (!(Date.now() - Date.parse(asked) < QFROM_MINUTES * 60e3)) return false;
  const { items } = searchArchive(await archive(env), text, 8);
  if (!items.length) {
    await tg(env, "sendMessage", { chat_id: uid, text: `Среди обзоров такого не нашёл, поэтому список не начал (чтобы выбрать снова, нажми «${QUEUE_BUTTON}»). Ищу как обычно:` });
    return false;
  }
  if (items.length === 1) await sendQueue(env, uid, { fromId: items[0].id, confirmed: true });
  else await tg(env, "sendMessage", { chat_id: uid, text: "Какой из них?",
    reply_markup: { inline_keyboard: albumButtons(items, true).map(([b]) => [{ ...b, callback_data: `qf:${b.callback_data.slice(2)}` }]) } });
  return true;
}

// A «Наверстать» card. section "l": from the «Послушать потом» block, "c": from the reviews after the place; when not
// given (a tap in the list), a review marked later is the block's.
async function openQueueCard(env, uid, id, section) {
  const arch = await archive(env);
  const a = arch.find((x) => x.id === id);
  if (!a) return tg(env, "sendMessage", { chat_id: uid, text: "Не нашёл этот альбом." });
  const statuses = statusMap(await userMarks(env, uid));
  const sec = section || (statuses[id] === "later" ? "l" : "c");
  if (sec === "l") {
    await queuePlace(env, uid, arch, statuses, true); // the place is fixed before this album gets marked heard
    const block = laterReviews(arch, await laterIds(env, uid));
    const left = block.length - 1 - block.findIndex((x) => x.id === a.id);
    return sendAlbum(env, uid, a, `▶ <i>Наверстываю · послушать потом${left ? `, после этого ещё ${left}` : ", это последний, потом новые обзоры"}</i>`, { queue: "l" });
  }
  const left = after(arch, a).length;
  return sendAlbum(env, uid, a, `▶ <i>Наверстываю${left ? ` · после этого ещё ${reviewsWord(left)}` : " · это последний обзор"}</i>`, { queue: "c" });
}

// After a mark or «Пропустить →» on a «Наверстать» card: the next one in its part (in the «Послушать потом» block,
// nextLater, found before the mark). The block goes on to the reviews after the place; their end gets the trophy.
async function queueNext(env, uid, id, section = "c", nextLater = null) {
  const arch = await archive(env);
  const cur = arch.find((x) => x.id === id);
  const statuses = statusMap(await userMarks(env, uid));
  if (section === "l") {
    if (nextLater) return openQueueCard(env, uid, nextLater.id, "l");
    const from = await queuePlace(env, uid, arch, statuses, true);
    if (!from) return askQueueFrom(env, uid, true);
    const next = nextAfter(arch, from, statuses);
    if (next) return openQueueCard(env, uid, next.id, "c");
  } else {
    const next = cur && nextAfter(arch, cur, statuses);
    if (next) return openQueueCard(env, uid, next.id, "c");
  }
  const heard = Object.values(statuses).filter((s) => s === "done" || s === "nope").length;
  return tg(env, "sendMessage", { chat_id: uid, parse_mode: "HTML",
    text: `🏆 <b>Ты нагнал(а) всё до самого нового обзора Фантано!</b>\nУ тебя ${reviewsWord(heard)} с отметкой «прослушано». Новые обзоры будут в канале.` });
}


// Critic scores and charts for a review, from the site's rt/<id>.json (built from data/ratings.json; source:
// the album's Wikipedia article). null when there is none. One small fetch instead of parsing all ratings.
// The AI's mood guess for a card: the bot's own card (Gemini) first, else the archive brief's (lmn/briefs.py, in rt).
function cardMoods(full, rt, old = false) {
  const m = (full && full.ai && full.ai.moods && full.ai.moods.length ? full.ai.moods : rt && rt.moods) || [];
  // old: the list buttons sent before «Вайб для» (2026-11-02) counted in (v:<id>:<i>), kept for those buttons
  return old ? m.filter((x) => MOODS.includes(x)).slice(0, 2) : shownMoods(m).slice(0, 2);
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

// After «✓ Слушал»: one message with a list of similar albums, a card only for the one pressed (owner, 2026-11-02:
// as the channel's pinned list). Similar = Fantano's 8+ or CLASSIC with the most genre tags in common, rarer tags weighing
// more, not yet marked. Only genre tags count (genres.mjs: not labels, places or "vlog"), so these never match.
const SIMILAR_N = 6;
async function maybeSuggestSimilar(env, uid, rid) {
  const user = await env.DB.prepare("SELECT 1 FROM users WHERE user_id=?").bind(uid).first();
  if (!user) return; // can't write first to someone who never started the bot
  const m = await env.DB.prepare("SELECT score FROM marks WHERE user_id=? AND review_id=?").bind(uid, rid).first();
  if (m && m.score != null && m.score < 7) return; // they didn't like it
  const arch = await archive(env);
  const base = arch.find((a) => a.id === rid);
  const names = base ? null : (await markedNames(env, [rid]))[rid]; // an album without a review: just its name
  const title = base ? `${base.artist_name} — ${base.album}` : names ? `${names.artist_name} — ${names.album}` : "";
  const g = new Set(genresOf(base).map((x) => x.toLowerCase()));
  const marked = g.size ? await userMarks(env, uid) : {};
  // a rare tag in common says more than a common one: "shoegaze" counts for more than "rock" (weight log(N / reviews with it))
  const df = {};
  if (g.size) for (const a of arch) for (const x of a.genres || []) { const k = x.toLowerCase(); if (g.has(k)) df[k] = (df[k] || 0) + 1; }
  const weight = (k) => Math.log(arch.length / (df[k] || 1));
  const scored = arch.filter((a) => g.size && good(a) && a.id !== rid && !marked[a.id])
    .map((a) => ({ a, n: (a.genres || []).reduce((sum, x) => sum + (g.has(x.toLowerCase()) ? weight(x.toLowerCase()) : 0), 0), r: Math.random() }))
    .filter((x) => x.n > 0)
    .sort((x, y) => y.n - x.n || x.r - y.r); // the most in common first, a random pick among equals
  const chosen = scored.slice(0, SIMILAR_N).map((x) => x.a);
  const about = title ? ` на <b>${esc(title)}</b>` : "";
  if (!chosen.length) return tg(env, "sendMessage", { chat_id: uid, parse_mode: "HTML", text: `Пока не можем найти похожие${about}.` });
  return tg(env, "sendMessage", { chat_id: uid, parse_mode: "HTML",
    text: `Похожие${about} по жанрам. Нажми на альбом, пришлю карточку:`, reply_markup: { inline_keyboard: albumButtons(chosen, true) } });
}

// Four situations for this album: the AI's guess first, then the ones its genres suggest (a genre listed earlier in
// the album's tags and an earlier place in GENRE_MOODS weigh more), then common ones.
function genreMoods(r, ai = []) {
  const score = new Map();
  genresOf(r).forEach((g, gi) => {
    const tag = ` ${String(g).toLowerCase()} `;
    for (const [re, moods] of GENRE_RES) {
      if (!re.test(tag)) continue;
      moods.forEach((m, mi) => score.set(m, (score.get(m) || 0) + (4 - mi) / (gi + 1)));
      break;  // the first group a tag matches: "art pop" is art, not pop
    }
  });
  const byGenre = [...score.entries()].sort((a, b) => b[1] - a[1]).map(([m]) => m);
  return shownMoods([...ai, ...byGenre, ...DEFAULT_MOODS]).slice(0, 4);
}

async function askMood(env, uid, rid, all = false, messageId = null) {
  const r = (await reviews(env)).find((x) => x.id === rid) || (await archive(env)).find((x) => x.id === rid);
  if (!r) return;
  const ai = cardMoods(r, r.ai && r.ai.moods && r.ai.moods.length ? null : await criticsOf(env, rid));
  const shown = all ? Object.keys(VIBES) : genreMoods(r, ai);
  const buttons = shown.map((m) => ({ text: `для ${vibe(m)}`, callback_data: `vo:${rid}:${MOODS.indexOf(m)}` }));
  const rows = [];
  for (let i = 0; i < buttons.length; i += 2) rows.push(buttons.slice(i, i + 2));
  if (!all) rows.push([{ text: "Другие варианты", callback_data: `ma:${rid}` }]);
  const msg = { chat_id: uid, parse_mode: "HTML", text: `Для чего вайб у <b>${esc(r.artist_name)} — ${esc(r.album)}</b>?`,
    reply_markup: { inline_keyboard: rows } };
  if (messageId) return tg(env, "editMessageText", { ...msg, message_id: messageId });
  await tg(env, "sendMessage", msg);
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
  return { text: `🔔 Ты следишь за ${short(a.artist_name)}. О новом альбоме и новом обзоре напишу в личку.`, first };
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
// The Workers free plan allows 50 requests outside the Worker per run, and D1 queries count among them (and have their
// own limit of 50; a batch is one), so a run that messages many people does it in portions and leaves the rest for the
// next run. Nobody waits for these to the minute (owner, 2026-11-02: a day late is fine for news, days for a reminder).
const FOLLOW_BUDGET = 45; // one /api/new-reviews call
const DAILY_BUDGET = 45; // the daily cron: reminders, then old pinned lists

// «🔔 Новый обзор» to the people who follow this review's artist, as many as the budget allows.
// Returns { sent, done }: done = everyone who follows the artist has it now.
async function tellFollowers(env, r, budget) {
  if (!r || !r.id || !r.artist_name) return { sent: 0, done: true };
  if (budget.left < 5) return { sent: 0, done: false };
  budget.left -= 3; // the artist of the review, the follows, those already told
  const rid = String(r.id);
  await env.DB.prepare("INSERT INTO review_artists (review_id, artist_name, mbid) VALUES (?,?,?) " +
    "ON CONFLICT(review_id) DO UPDATE SET artist_name=excluded.artist_name, mbid=excluded.mbid").bind(rid, r.artist_name, r.mbid || null).run();
  const { results } = await env.DB.prepare("SELECT user_id, name_key, mbid FROM follows WHERE name_key=? OR mbid=?")
    .bind(nameKey(r.artist_name), r.mbid || "").all();
  const { results: told } = await env.DB.prepare("SELECT user_id FROM follow_sent WHERE review_id=?").bind(rid).all();
  const done = new Set(told.map((t) => String(t.user_id)));
  const todo = [];
  for (const f of results) {
    if (!followMatches(f, r) || done.has(String(f.user_id))) continue;
    done.add(String(f.user_id)); // a person may match by both the name and the ID
    todo.push(f.user_id);
  }
  const part = todo.slice(0, Math.max(0, budget.left - 1));
  if (!part.length) return { sent: 0, done: !todo.length };
  // the rows first, in one batch: a second call at the same time can't message these people again
  budget.left -= 1;
  const rows = await env.DB.batch(part.map((uid) =>
    env.DB.prepare("INSERT OR IGNORE INTO follow_sent (user_id, review_id, sent_at) VALUES (?,?,?)").bind(uid, rid, now())));
  const post = r.msg ? `https://t.me/${String(env.CHANNEL).replace(/^@/, "")}/${r.msg}` : null;
  let sent = 0;
  for (let i = 0; i < part.length; i++) {
    if (!rows[i] || !rows[i].meta || !rows[i].meta.changes) continue;
    budget.left -= 1;
    const d = await tg(env, "sendMessage", {
      chat_id: part[i], parse_mode: "HTML",
      text: `🔔 Новый обзор: <b>${esc(r.artist_name)} — ${esc(r.album)}</b>${r.score ? ", " + esc(r.score) : ""}`,
      ...(post ? { reply_markup: { inline_keyboard: [[{ text: "Карточка в канале", url: post }]] } } : {}),
    });
    if (d.ok) sent++;
  }
  return { sent, done: part.length === todo.length };
}

// ---------- new releases of followed artists (hourly cron, releases.mjs) ----------

const RELEASES_CRON = "30 * * * *";
const RELEASE_BUDGET = 40; // requests outside Cloudflare per run: the Workers free plan allows 50
const RELEASE_CARD_COST = 7; // Deezer album, archive, reviews, Wikipedia (up to 3), Apple

// Each run: first tell followers about albums found earlier (one card per album, sent to each follower once), then
// check a few followed artists that weren't checked for RECHECK_HOURS. Quiet hours: checks only, the news waits.
async function watchReleases(env, when) {
  const budget = { left: RELEASE_BUDGET };
  const quiet = quietHour(when);
  if (!quiet) await tellNewReleases(env, budget); // news found earlier goes first
  await checkArtists(env, when, budget);
  if (!quiet) await tellNewReleases(env, budget); // then this run's, if requests are left
}

async function tellNewReleases(env, budget) {
  const since = new Date(Date.now() - 3 * 864e5).toISOString(); // news older than 3 days isn't news
  const { results } = await env.DB.prepare("SELECT dz_id, name_key, artist_name, title, release_date FROM new_releases WHERE found_at>=? ORDER BY found_at").bind(since).all();
  let arch = null;
  let recent = null;
  for (const n of results) {
    const rid = `nr:${n.dz_id}`;
    const { results: who } = await env.DB.prepare(
      "SELECT f.user_id FROM follows f WHERE f.name_key=? AND NOT EXISTS (SELECT 1 FROM follow_sent s WHERE s.user_id=f.user_id AND s.review_id=?)")
      .bind(n.name_key, rid).all();
    if (!who.length) continue;
    if (budget.left < RELEASE_CARD_COST + 1) return;
    budget.left -= 3; // the album at Deezer, archive.json, reviews.json
    arch = arch || await archive(env);
    recent = recent || await reviews(env);
    // Fantano got there first (a review before the release): the usual «Новый обзор» message covers it
    if (reviewedIn(arch, n.artist_name, n.title) || reviewedIn(recent, n.artist_name, n.title)) {
      for (const f of who) await env.DB.prepare("INSERT OR IGNORE INTO follow_sent (user_id, review_id, sent_at) VALUES (?,?,?)").bind(f.user_id, rid, now()).run();
      continue;
    }
    const d = await deezerJson(`album/${n.dz_id}`);
    if (!d.id) continue;
    budget.left -= RELEASE_CARD_COST - 3;
    const ep = d.record_type === "ep";
    const card = await unreviewedCard(env, {
      key: `dz${d.id}`, artist: (d.artist && d.artist.name) || n.artist_name, title: d.title, year: "", kind: ep ? "EP" : "",
      genres: ((d.genres && d.genres.data) || []).map((g) => g.name), tracks: d.nb_tracks, minutes: d.duration ? Math.round(d.duration / 60) : null,
      cover: d.cover_xl || d.cover_big, fresh: n.release_date,
      intro: `🔔 Новый ${ep ? "EP" : "альбом"} артиста, за которым ты следишь`,
    }, arch);
    // as many followers as the budget allows, their rows in one batch first; the rest get it next hour
    const part = who.slice(0, Math.floor((budget.left - 1) / 2));
    if (!part.length) return;
    budget.left -= 1;
    const rows = await env.DB.batch(part.map((f) =>
      env.DB.prepare("INSERT OR IGNORE INTO follow_sent (user_id, review_id, sent_at) VALUES (?,?,?)").bind(f.user_id, rid, now())));
    for (let i = 0; i < part.length; i++) {
      if (!rows[i] || !rows[i].meta || !rows[i].meta.changes) continue;
      budget.left -= 2; // a photo, and a text message if the photo fails
      await sendCard(env, part[i].user_id, card);
    }
    if (part.length < who.length) return;
  }
}

async function checkArtists(env, when, budget) {
  // every followed artist gets a row; a row whose followers all left stays and is just not checked
  await env.DB.prepare("INSERT OR IGNORE INTO watched_artists (name_key, artist_name) SELECT name_key, MIN(artist_name) FROM follows GROUP BY name_key").run();
  const due = new Date(when.getTime() - RECHECK_HOURS * 3600e3).toISOString();
  const { results } = await env.DB.prepare(
    "SELECT w.name_key, w.artist_name, w.dz_id, w.seen FROM watched_artists w WHERE (w.checked_at IS NULL OR w.checked_at<?) " +
    "AND EXISTS (SELECT 1 FROM follows f WHERE f.name_key=w.name_key) ORDER BY w.checked_at IS NOT NULL, w.checked_at LIMIT 20").bind(due).all();
  let lists = null;
  for (const w of results) {
    // a known Deezer artist costs 1 request; finding it up to 2 + 2×3 more (deezerAlbum: 2 searches and the album)
    if (budget.left < (w.dz_id == null ? 9 : 1)) return;
    let dz = w.dz_id;
    if (dz == null) {
      // the Deezer artist is the one whose album Fantano reviewed: a name alone mixes up bands called the same
      if (!lists) {
        budget.left -= 2;
        lists = [...(await reviews(env)), ...(await archive(env))];
      }
      const theirs = lists.filter((a) => nameKey(a.artist_name) === w.name_key && a.album)
        .sort((a, b) => String(b.published).localeCompare(String(a.published)));
      for (const a of theirs.slice(0, 2)) {
        budget.left -= 3;
        const hit = await deezerAlbum(a.artist_name, untitled(a.album));
        if (hit && hit.artistId) { dz = hit.artistId; break; }
      }
      if (dz) await env.DB.prepare("UPDATE watched_artists SET dz_id=? WHERE name_key=?").bind(dz, w.name_key).run();
    }
    if (!dz) {
      // not found (MusicBrainz-only artist, or Deezer spells it differently): tried again in a week
      const week = new Date(when.getTime() + (7 * 24 - RECHECK_HOURS) * 3600e3).toISOString();
      await env.DB.prepare("UPDATE watched_artists SET checked_at=? WHERE name_key=?").bind(week, w.name_key).run();
      continue;
    }
    budget.left -= 1;
    const albums = await deezerFresh(`artist/${dz}/albums?limit=100`);
    if (!albums) continue; // Deezer didn't answer: next run
    const { fresh, seen } = sortOut(albums, w.seen ? JSON.parse(w.seen) : null, when);
    for (const a of fresh) {
      await env.DB.prepare("INSERT OR IGNORE INTO new_releases (dz_id, name_key, artist_name, title, release_date, found_at) VALUES (?,?,?,?,?,?)")
        .bind(a.id, w.name_key, w.artist_name, a.title, a.release_date, now()).run();
    }
    await env.DB.prepare("UPDATE watched_artists SET seen=?, checked_at=? WHERE name_key=?").bind(JSON.stringify(seen), when.toISOString(), w.name_key).run();
  }
}

// Deezer's list without Cloudflare's day-long cache (deezerJson's): a new album must show up the day it's out.
async function deezerFresh(path) {
  try {
    const r = await fetch(`https://api.deezer.com/${path}`);
    const d = r.ok ? await r.json() : null;
    return d && Array.isArray(d.data) ? d.data : null;
  } catch (e) {
    return null;
  }
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

// ---------- "⏳ Послушать потом", "♥ Понравившееся" and "▶ Отрывки" ----------

// What marked IDs are: a review (archive), or an album without one (a MusicBrainz release group, or "dz<Deezer id>").
// -> { id: { artist_name, album, open: the callback that opens its card } }
async function markedNames(env, ids) {
  const out = {};
  if (!ids.length) return out;
  const want = new Set(ids);
  for (const a of await archive(env)) if (want.has(a.id)) out[a.id] = { artist_name: a.artist_name, album: a.album, open: `a:${a.id}`, badge: badge(a) };
  for (const r of await reviews(env)) if (want.has(r.id) && !out[r.id]) out[r.id] = { artist_name: r.artist_name, album: r.album, open: `a:${r.id}`, badge: badge(r) };
  const rest = ids.filter((id) => !out[id]);
  for (let i = 0; i < rest.length; i += 50) {
    const part = rest.slice(i, i + 50);
    const { results } = await env.DB.prepare(`SELECT id, artist_name, album FROM unreviewed WHERE id IN (${part.map(() => "?").join(",")})`).bind(...part).all();
    for (const u of results) out[u.id] = { artist_name: u.artist_name, album: u.album, open: u.id.startsWith("dz") ? `dz:${u.id.slice(2)}` : `mb:${u.id}` };
  }
  return out;
}

async function sendLater(env, uid) {
  const { results } = await env.DB.prepare("SELECT review_id FROM marks WHERE user_id=? AND status='later' ORDER BY later_at, rowid").bind(uid).all();
  if (!results.length) {
    return tg(env, "sendMessage", { chat_id: uid, text: "Тут пусто. Нажми «⏳ Послушать потом» под любой карточкой, и альбом появится здесь. Они же идут первыми в «" + QUEUE_BUTTON + "»." });
  }
  const names = await markedNames(env, results.map((r) => r.review_id));
  const items = results.map((r) => names[r.review_id]).filter(Boolean);
  const shown = items.slice(0, 40);
  return tg(env, "sendMessage", {
    chat_id: uid,
    text: `Послушать потом: ${items.length}${items.length > shown.length ? ` (показаны первые ${shown.length})` : ""}. Сверху то, что отложено раньше; в том же порядке они идут первыми в «${QUEUE_BUTTON}». Через 3 недели напомню о каждом, не чаще раза в неделю.`,
    reply_markup: { inline_keyboard: shown.map((x) => [{ text: `⏳ ${short(x.artist_name)} — ${short(x.album)}`.slice(0, 120), callback_data: x.open }]) },
  });
}

// «♥ Понравившееся» (owner, 2026-11-02: «чтобы я потом мог себе загрузить альбомы эти, купить диски»; «мне надо
// именно ключевая информация автор название, ну и как обычно что там, чтобы я вспомнил альбом»): the last liked first,
// PAGE lines a message as in «Наверстать» (colour and score · Artist — Album, a link to its card · genre · review date),
// «Дальше ▸» edits the same message.
async function sendLiked(env, uid, offset = 0, edit) {
  const { results } = await env.DB.prepare("SELECT review_id FROM likes WHERE user_id=? ORDER BY liked_at DESC, rowid DESC").bind(uid).all();
  if (!results.length) {
    return tg(env, "sendMessage", { chat_id: uid, text: "Тут пусто. Нажми «♡ Понравилось» под карточкой альбома, и он появится здесь. Эту отметку не стирают ни «Слушал», ни «Послушать потом»." });
  }
  const arch = await archive(env);
  const byId = new Map(arch.map((a) => [a.id, a]));
  const page = results.slice(offset, offset + PAGE).map((r) => r.review_id);
  const names = await markedNames(env, page.filter((id) => !byId.has(id)));
  const lines = page.map((id) => {
    const a = byId.get(id);
    if (a) return queueLine(a, startLink(env, `a:${id}`), esc);
    const x = names[id]; // an album without Fantano's review
    return x ? `⚪ · <a href="${startLink(env, x.open)}">${esc(x.artist_name)} — ${esc(x.album)}</a> · без обзора Фантано` : null;
  }).filter(Boolean);
  const more = offset + PAGE < results.length;
  const text = `<b>${LIKED_BUTTON}</b> · ${results.length}${results.length > PAGE ? `, здесь ${offset + 1}–${offset + page.length}` : ""}\n\n` +
    lines.join("\n") + "\n\nНажми на альбом: пришлю его карточку.";
  const nav = [];
  if (offset) nav.push({ text: "◂ Назад", callback_data: `lp:${Math.max(0, offset - PAGE)}` });
  if (more) nav.push({ text: "Дальше ▸", callback_data: `lp:${offset + PAGE}` });
  return tg(env, edit ? "editMessageText" : "sendMessage", { chat_id: uid, ...(edit ? { message_id: edit } : {}), text, parse_mode: "HTML",
    link_preview_options: { is_disabled: true }, reply_markup: { inline_keyboard: nav.length ? [nav] : [] } });
}

// ---------- reminders (daily cron) ----------

// The daily cron removes a few pinned lists left in private chats a day (dropDmPin; since 2026-11-02 there are none),
// a cursor in settings remembers the last one.
async function migrateDmPins(env, budget) {
  const perRun = Math.min(10, Math.floor((budget.left - 3) / 4)); // a pinned list: its row, unpin, delete, the row again
  if (perRun < 1) return;
  const after = Number((await getSetting(env, "dm_pins_v3_after")) || 0);
  if (after < 0) return; // all done
  const { results } = await env.DB.prepare("SELECT user_id FROM users WHERE dm_pinned_id IS NOT NULL AND user_id > ? ORDER BY user_id LIMIT ?")
    .bind(after, perRun).all();
  for (const u of results) await dropDmPin(env, u.user_id);
  await setSetting(env, "dm_pins_v3_after", String(results.length < perRun ? -1 : results[results.length - 1].user_id));
}

async function sendReminders(env, budget) {
  const cutoff = new Date(Date.now() - 21 * 864e5).toISOString();
  const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString();
  budget.left -= 1;
  const { results } = await env.DB.prepare(
    "SELECT m.user_id, m.review_id FROM marks m JOIN users u ON u.user_id=m.user_id " +
      "WHERE m.status='later' AND m.later_at <= ? AND m.reminded_at IS NULL " +
      "AND NOT EXISTS (SELECT 1 FROM marks x WHERE x.user_id=m.user_id AND x.reminded_at > ?) ORDER BY m.later_at"
  ).bind(cutoff, weekAgo).all();
  // one reminder per person (the first put off), as many people as the budget allows: the rest are reminded tomorrow
  const seen = new Set();
  const due = results.filter((row) => !seen.has(row.user_id) && seen.add(row.user_id));
  const part = due.slice(0, Math.max(0, budget.left - 4)); // archive.json, reviews.json, maybe a D1 query; the batch
  if (!part.length) return;
  budget.left -= 3;
  const names = await markedNames(env, part.map((r) => r.review_id));
  const sent = [];
  for (const row of part) {
    const r = names[row.review_id];
    if (!r) continue;
    budget.left -= 1;
    await tg(env, "sendMessage", {
      chat_id: row.user_id,
      parse_mode: "HTML",
      text: `Три недели назад ты добавил(а) <b>${esc(r.artist_name)} — ${esc(r.album)}</b> в «Послушать потом». Самое время?`,
      reply_markup: { inline_keyboard: [[{ text: "✓ Слушал", callback_data: `m:${row.review_id}:done` }, { text: "Открыть", callback_data: r.open }]] },
    });
    sent.push(row);
  }
  if (!sent.length) return;
  budget.left -= 1;
  const at = now();
  await env.DB.batch(sent.map((row) => env.DB.prepare("UPDATE marks SET reminded_at=? WHERE user_id=? AND review_id=?").bind(at, row.user_id, row.review_id)));
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
