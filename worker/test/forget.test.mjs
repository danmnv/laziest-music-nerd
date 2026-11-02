// /forget: one confirmation, then nothing about the person is left in D1; other people's rows stay.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHmac } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";

const ME = 7, OTHER = 8;
const SCHEMA = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
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

function seed(uid, pinned) {
  db.prepare("INSERT INTO users (user_id, dm_pinned_id, started_at) VALUES (?,?,?)").run(uid, pinned, "2026-11-01");
  db.prepare("INSERT INTO marks (user_id, review_id, status, updated_at) VALUES (?,?,?,?)").run(uid, "k", "later", "2026-11-01");
  db.prepare("INSERT INTO likes (user_id, review_id, liked_at) VALUES (?,?,?)").run(uid, "k", "2026-11-01");
  db.prepare("INSERT INTO mood_votes (user_id, review_id, mood, vote) VALUES (?,?,?,?)").run(uid, "k", "ночь", "y");
  db.prepare("INSERT INTO follows (user_id, name_key, artist_name, created_at) VALUES (?,?,?,?)").run(uid, "radiohead", "Radiohead", "2026-11-01");
  db.prepare("INSERT INTO follow_sent (user_id, review_id, sent_at) VALUES (?,?,?)").run(uid, "nr:9", "2026-11-01");
  for (const k of ["menu", "qpos", "qfrom"]) db.prepare("INSERT INTO settings (key, value) VALUES (?,?)").run(`${k}:${uid}`, "1");
}

const rowsOf = (uid) => Object.fromEntries(["users", "marks", "likes", "mood_votes", "follows", "follow_sent"]
  .map((t) => [t, db.prepare(`SELECT COUNT(*) AS n FROM ${t} WHERE user_id=?`).get(uid).n]));
const settingsOf = (uid) => db.prepare("SELECT COUNT(*) AS n FROM settings WHERE key LIKE ?").get(`%:${uid}`).n;

async function send(update) {
  await worker.fetch(new Request("https://w/tg", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "w" }, body: JSON.stringify(update) }),
    env, { waitUntil: (p) => p });
  await new Promise((r) => setTimeout(r, 20));
}
const say = (text) => send({ message: { message_id: 1, chat: { id: ME, type: "private" }, from: { id: ME }, text } });
const press = (data) => send({ callback_query: { id: "q", from: { id: ME }, data, message: { message_id: 50, chat: { id: ME } } } });

beforeEach(() => {
  db = new DatabaseSync(":memory:");
  db.exec(SCHEMA);
  seed(ME, 33);
  seed(OTHER, null);
  calls = [];
  env = { DB: d1(db), WEBHOOK_SECRET: "w", BOT_USERNAME: "bot", CHANNEL: "@chan", TELEGRAM_BOT_TOKEN: "t", OWNER_ID: "1", SESSION_SECRET: "s" };
  globalThis.fetch = async (url, opts) => {
    calls.push({ method: String(url).split("/").pop(), ...JSON.parse(opts.body) });
    return new Response(JSON.stringify({ ok: true, result: { message_id: 600 } }));
  };
});

test("/forget only asks; nothing is deleted before the button", async () => {
  await say("/forget");
  const ask = calls.find((c) => c.method === "sendMessage" && c.reply_markup && c.reply_markup.inline_keyboard);
  assert.deepEqual(ask.reply_markup.inline_keyboard[0].map((b) => b.callback_data), ["fg:y", "fg:n"]);
  assert.equal(rowsOf(ME).marks, 1);
  await press("fg:n");
  assert.deepEqual(rowsOf(ME), { users: 1, marks: 1, likes: 1, mood_votes: 1, follows: 1, follow_sent: 1 });
});

test("«Да, удалить всё» leaves no row about the person and keeps everyone else's", async () => {
  await press("fg:y");
  assert.deepEqual(rowsOf(ME), { users: 0, marks: 0, likes: 0, mood_votes: 0, follows: 0, follow_sent: 0 });
  assert.equal(settingsOf(ME), 0);
  assert.deepEqual(rowsOf(OTHER), { users: 1, marks: 1, likes: 1, mood_votes: 1, follows: 1, follow_sent: 1 });
  assert.equal(settingsOf(OTHER), 3);
  // the old pinned list in the chat goes too, and the menu keyboard is taken away
  assert.ok(calls.some((c) => c.method === "unpinChatMessage" && c.message_id === 33));
  assert.ok(calls.some((c) => c.method === "sendMessage" && c.reply_markup && c.reply_markup.remove_keyboard));
});

test("every table with a user_id column is wiped by /forget", () => {
  // a new per-person table must be added to USER_TABLES in index.js and to rowsOf here
  const withUser = SCHEMA.split("CREATE TABLE IF NOT EXISTS ").slice(1)
    .filter((t) => /\buser_id\b/.test(t.split("\n);")[0])).map((t) => t.split(" ")[0]).sort();
  const src = readFileSync(new URL("../src/index.js", import.meta.url), "utf8");
  const listed = JSON.parse(src.match(/const USER_TABLES = (\[[^\]]*\])/)[1]).sort();
  assert.deepEqual(withUser, listed);
});

test("the help says what is stored and how to delete it", async () => {
  await say("/help");
  const help = calls.find((c) => c.method === "sendMessage" && c.text.includes("Что я храню"));
  assert.ok(help && help.text.includes("/forget"));
  assert.ok(help.text.length < 4096);
});

// The help promises that a mark can be taken back; taking it back must leave no row (the owner, 2026-11-02)
test("a mark pressed again in the bot is deleted, not emptied", async () => {
  await press("m:k:later");
  assert.equal(rowsOf(ME).marks, 0);
  assert.equal(rowsOf(OTHER).marks, 1);
});

async function site(body) {
  const exp = Math.floor(Date.now() / 1000) + 3600;
  const token = `${ME}.${exp}.` + createHmac("sha256", "s").update(`${ME}.${exp}`).digest("hex");
  const r = await worker.fetch(new Request("https://w/api/mark", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(body) }),
    { ...env, SITE_URL: "https://site.example/" }, { waitUntil: (p) => p });
  assert.equal(r.status, 200);
}

test("on the site a second press and «—» clear the mark and the score", async () => {
  await site({ review_id: "k", score: 7 });
  assert.deepEqual({ ...db.prepare("SELECT status, score FROM marks WHERE user_id=?").get(ME) }, { status: "later", score: 7 });
  await site({ review_id: "k", status: null });
  assert.deepEqual({ ...db.prepare("SELECT status, score FROM marks WHERE user_id=?").get(ME) }, { status: null, score: 7 });
  await site({ review_id: "k", score: null });
  assert.equal(rowsOf(ME).marks, 0);
});
