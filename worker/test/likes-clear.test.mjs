// «🗑 Очистить список» under «♥ Понравившееся»: a question first, then only this person's likes go, nothing else.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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

async function press(data) {
  const update = { callback_query: { id: "q", from: { id: ME }, data, message: { message_id: 50, chat: { id: ME } } } };
  await worker.fetch(new Request("https://w/tg", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "w" }, body: JSON.stringify(update) }),
    env, { waitUntil: (p) => p });
  await new Promise((r) => setTimeout(r, 20));
}
const likes = (uid) => db.prepare("SELECT review_id FROM likes WHERE user_id=? ORDER BY review_id").all(uid).map((r) => r.review_id);
const lastEdit = () => calls.filter((c) => c.method === "editMessageText").pop();

beforeEach(() => {
  db = new DatabaseSync(":memory:");
  db.exec(SCHEMA);
  for (const uid of [ME, OTHER]) {
    db.prepare("INSERT INTO users (user_id, started_at) VALUES (?,?)").run(uid, "2026-11-01");
    for (const id of ["a", "b", "c"]) db.prepare("INSERT INTO likes (user_id, review_id, liked_at) VALUES (?,?,?)").run(uid, id, "2026-11-01T10:00:00.000Z");
    db.prepare("INSERT INTO marks (user_id, review_id, status, updated_at) VALUES (?,?,?,?)").run(uid, "a", "done", "2026-11-01");
  }
  calls = [];
  env = { DB: d1(db), WEBHOOK_SECRET: "w", BOT_USERNAME: "bot", CHANNEL: "@chan", TELEGRAM_BOT_TOKEN: "t", OWNER_ID: "1", SESSION_SECRET: "s" };
  globalThis.fetch = async (url, opts) => {
    calls.push({ method: String(url).split("/").pop(), ...JSON.parse(opts.body) });
    return new Response(JSON.stringify({ ok: true, result: { message_id: 600 } }));
  };
});

test("the button only asks, with the count; nothing is deleted yet", async () => {
  await press("lc");
  const ask = lastEdit();
  assert.match(ask.text, /Убрать все 3 альбома/);
  const [yes, no] = ask.reply_markup.inline_keyboard[0];
  assert.match(yes.callback_data, /^lc:y:\d+$/);
  assert.equal(no.callback_data, "lc:n");
  assert.deepEqual(likes(ME), ["a", "b", "c"]);
});

test("«Да» clears this person's likes only; marks and other people's likes stay", async () => {
  await press(`lc:y:${Date.now()}`);
  assert.deepEqual(likes(ME), []);
  assert.deepEqual(likes(OTHER), ["a", "b", "c"]);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM marks WHERE user_id=?").get(ME).n, 1);
  assert.match(lastEdit().text, /убрал из «Понравившееся» 3 альбома/);
});

test("a like added after the question was asked survives «Да»", async () => {
  const asked = Date.parse("2026-11-02T00:00:00Z");
  db.prepare("INSERT INTO likes (user_id, review_id, liked_at) VALUES (?,?,?)").run(ME, "d", "2026-11-03T00:00:00.000Z");
  await press(`lc:y:${asked}`);
  assert.deepEqual(likes(ME), ["d"]);
});

test("an empty list says so instead of asking", async () => {
  db.prepare("DELETE FROM likes WHERE user_id=?").run(ME);
  await press("lc");
  assert.match(lastEdit().text, /и так пуст/);
  assert.deepEqual(lastEdit().reply_markup.inline_keyboard, []);
});
