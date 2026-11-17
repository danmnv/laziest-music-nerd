// «🗑 Очистить список» under «♥ Понравившееся».
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";

const ME = 7, OTHER = 8;
const SCHEMA = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");
const LIKED_AT = "2026-11-01T10:00:00.000Z";
let db, calls, env, afterSnapshot;

function d1(sqlite) {
  return {
    async batch(statements) {
      sqlite.exec("BEGIN");
      const results = [];
      try {
        for (const statement of statements) results.push(await statement.run());
        sqlite.exec("COMMIT");
      } catch (error) {
        sqlite.exec("ROLLBACK");
        throw error;
      }
      afterSnapshot?.();
      return results;
    },
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

async function press(data, uid = ME) {
  const update = { callback_query: { id: "q", from: { id: uid }, data, message: { message_id: 50, chat: { id: uid } } } };
  let task;
  const response = await worker.fetch(
    new Request("https://w/tg", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "w" }, body: JSON.stringify(update) }),
    env, { waitUntil: (p) => { task = p; } },
  );
  assert.equal(response.status, 200);
  assert.ok(task);
  await task;
}

const likes = (uid) => db.prepare("SELECT review_id FROM likes WHERE user_id=? ORDER BY review_id").all(uid).map((r) => r.review_id);
const marks = () => db.prepare("SELECT * FROM marks ORDER BY user_id, review_id").all();
const addLike = (uid, id) => db.prepare("INSERT INTO likes (user_id, review_id, liked_at) VALUES (?,?,?)").run(uid, id, LIKED_AT);
const lastEdit = () => calls.filter((c) => c.method === "editMessageText").pop();

async function ask() {
  await press("lc");
  const [yes, no] = lastEdit().reply_markup.inline_keyboard[0];
  return [yes.callback_data, no.callback_data];
}

beforeEach(() => {
  db = new DatabaseSync(":memory:");
  db.exec(SCHEMA);
  for (const uid of [ME, OTHER]) {
    db.prepare("INSERT INTO users (user_id, started_at) VALUES (?,?)").run(uid, "2026-11-01");
    for (const id of ["a", "b", "c"]) addLike(uid, id);
    const addMark = db.prepare("INSERT INTO marks (user_id, review_id, status, updated_at) VALUES (?,?,?,?)");
    addMark.run(uid, "a", "done", "2026-11-01");
    addMark.run(uid, "b", "later", "2026-11-01");
  }
  afterSnapshot = null;
  calls = [];
  env = { DB: d1(db), WEBHOOK_SECRET: "w", BOT_USERNAME: "bot", CHANNEL: "@chan", TELEGRAM_BOT_TOKEN: "t", OWNER_ID: "1", SESSION_SECRET: "s", DATA_URL: "https://data.test/reviews.json" };
  globalThis.fetch = async (url, opts) => {
    const path = String(url).split("/").pop();
    if (path === "archive.json") {
      return Response.json(["a", "b", "c"].map((id) => ({ id, artist_name: "Artist", album: "Album " + id })));
    }
    if (path === "archive.min.json") return new Response(null, { status: 404 });
    calls.push({ method: path, ...JSON.parse(opts.body) });
    return Response.json({ ok: true, result: { message_id: 600 } });
  };
});

test("the button only asks, with the count; nothing is deleted yet", async () => {
  const [yes, no] = await ask();
  assert.match(lastEdit().text, /Убрать все 3 альбома/);
  assert.match(yes, /^lc:y:[0-9a-f-]{36}$/);
  assert.equal(no, "lc:n:" + yes.split(":")[2]);
  assert.deepEqual(likes(ME), ["a", "b", "c"]);
});

test("a like added after the snapshot but before the question is displayed survives", async () => {
  const before = marks();
  // Simulate a concurrent write after D1 took the snapshot and before its result reaches the Worker.
  // It has the same timestamp as the three existing likes.
  afterSnapshot = () => addLike(ME, "d");
  const [yes] = await ask();
  assert.match(lastEdit().text, /Убрать все 3 альбома/);
  assert.deepEqual(likes(ME), ["a", "b", "c", "d"]);
  await press(yes, OTHER);
  assert.deepEqual(likes(OTHER), ["a", "b", "c"]);
  await press(yes);
  assert.match(lastEdit().text, /убрал из «Понравившееся» 3 альбома/);
  assert.deepEqual(likes(ME), ["d"]);
  assert.deepEqual(marks(), before);
  await press(yes);
  assert.deepEqual(likes(ME), ["d"]);
});

test("an album unliked and liked again is excluded, even with the same timestamp", async () => {
  const [yes] = await ask();
  db.prepare("DELETE FROM likes WHERE user_id=? AND review_id=?").run(ME, "a");
  addLike(ME, "a");
  await press(yes);
  assert.match(lastEdit().text, /убрал из «Понравившееся» 2 альбома/);
  assert.deepEqual(likes(ME), ["a"]);
});

test("cancelling returns the list and closes the confirmation", async () => {
  const [yes, no] = await ask();
  await press(no);
  assert.match(lastEdit().text, /Понравившееся<\/b> · 3/);
  await press(yes);
  assert.deepEqual(likes(ME), ["a", "b", "c"]);
});

test("opening a new confirmation closes the previous one", async () => {
  const [oldYes, oldNo] = await ask();
  const [newYes] = await ask();
  await press(oldYes);
  assert.deepEqual(likes(ME), ["a", "b", "c"]);
  await press(oldNo);
  await press(newYes);
  assert.deepEqual(likes(ME), []);
});

test("an empty list says so instead of asking", async () => {
  db.prepare("DELETE FROM likes WHERE user_id=?").run(ME);
  await press("lc");
  assert.match(lastEdit().text, /и так пуст/);
  assert.deepEqual(lastEdit().reply_markup.inline_keyboard, []);
});
