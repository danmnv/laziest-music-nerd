// The watchdog: the owner hears when checks of new reviews go quiet, when a job asks to tell them, and before the data
// tokens end. Against an in-memory SQLite standing in for D1 and a fake Telegram.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";
import { silentFor, daysLeft } from "../src/watchdog.mjs";

const OWNER = 1;
let db, env, sent;

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

beforeEach(() => {
  db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  sent = [];
  env = { DB: d1(db), ACTIONS_SECRET: "a", TELEGRAM_BOT_TOKEN: "t", OWNER_ID: String(OWNER), SITE_URL: "https://site",
          DATA_URL: "https://data/reviews.json", CODE_REPO: "o/code", DATA_TOKEN_EXPIRES: "2027-10-31" };
  globalThis.fetch = async (url, opts) => {
    if (String(url).startsWith("https://api.telegram.org/")) {
      const m = String(url).split("/").pop();
      if (m === "sendMessage") sent.push(JSON.parse(opts.body));
      return new Response(JSON.stringify({ ok: true, result: { message_id: 1 } }));
    }
    return new Response("[]");
  };
});

const at = (day, hour) => Date.UTC(2026, 10, day, hour, 30);
const run = async (cron, time) => { const ps = []; await worker.scheduled({ cron, scheduledTime: time }, env, { waitUntil: (p) => ps.push(p) }); await Promise.all(ps); };
const hourly = (day, hour) => run("30 * * * *", at(day, hour));
const post = (path, body, secret = "a") => worker.fetch(new Request(`https://w${path}`, { method: "POST", headers: { Authorization: `Bearer ${secret}` }, body: JSON.stringify(body || {}) }), env, { waitUntil() {} });
const setting = (key) => db.prepare("SELECT value FROM settings WHERE key=?").get(key)?.value;
const seen = (iso) => db.prepare("INSERT INTO settings (key, value) VALUES ('check_seen', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").run(iso);

test("silentFor: quiet under 3 hours, then the hours; once a day while it lasts", () => {
  const now = new Date("2026-11-10T12:00:00Z");
  assert.equal(silentFor(null, null, now), 0);
  assert.equal(silentFor("2026-11-10T09:30:00Z", null, now), 0);
  assert.equal(silentFor("2026-11-10T08:10:00Z", "", now), 3);
  assert.equal(silentFor("2026-11-09T08:10:00Z", "2026-11-10T02:00:00Z", now), 0);
  assert.equal(silentFor("2026-11-08T08:10:00Z", "2026-11-09T11:30:00Z", now), 51);
});

test("daysLeft counts whole days to the tokens' last day", () => {
  assert.equal(daysLeft("2027-10-31", new Date("2027-10-01T09:00:00Z")), 30);
  assert.equal(daysLeft("2027-10-31", new Date("2027-10-31T23:00:00Z")), 0);
  assert.equal(daysLeft("", new Date()), null);
});

test("the first hourly run only starts the count; a check that keeps reporting means no message", async () => {
  await hourly(10, 10);
  assert.equal(setting("check_seen"), new Date(at(10, 10)).toISOString());
  assert.equal((await post("/api/heartbeat")).status, 200);
  await hourly(10, 11);
  await hourly(10, 12);
  assert.equal(sent.length, 0);
});

test("checks silent for 3 hours: the owner is told once, again a day later, and when they are back", async () => {
  seen("2026-11-10T08:00:00.000Z");
  await hourly(10, 10); // 2.5 h
  assert.equal(sent.length, 0);
  await hourly(10, 11); // 3.5 h
  assert.equal(sent.length, 1);
  assert.equal(sent[0].chat_id, OWNER);
  assert.match(sent[0].text, /молчит уже 3 ч/);
  assert.match(sent[0].text, /github\.com\/o\/code\/actions/);
  await hourly(10, 12);
  await hourly(10, 20);
  assert.equal(sent.length, 1);
  await hourly(11, 12); // a day after the first message
  assert.equal(sent.length, 2);
  assert.equal((await post("/api/heartbeat")).status, 200);
  assert.match(sent[2].text, /снова работает/);
  assert.equal(setting("check_alerted"), "");
  seen("2026-11-11T12:40:00.000Z"); // the heartbeat wrote the real clock's time; the test's clock is its own
  await hourly(11, 13);
  assert.equal(sent.length, 3);
});

test("at night the message waits for the morning (01:00–09:00 Moscow)", async () => {
  seen("2026-11-10T18:00:00.000Z");
  await hourly(10, 23); // 02:30 Moscow
  await hourly(11, 3);
  assert.equal(sent.length, 0);
  await hourly(11, 6); // 09:30 Moscow
  assert.equal(sent.length, 1);
});

test("/api/heartbeat and /api/alert need the Actions secret", async () => {
  assert.equal((await post("/api/heartbeat", {}, "wrong")).status, 403);
  assert.equal((await post("/api/alert", { kind: "llm" }, "wrong")).status, 403);
  assert.equal(setting("check_seen"), undefined);
  assert.equal(sent.length, 0);
});

test("/api/alert sends one of the known texts and nothing of the caller's", async () => {
  assert.equal((await post("/api/alert", { kind: "llm", code: 402 })).status, 200);
  assert.match(sent[0].text, /Selectel/);
  assert.match(sent[0].text, /код 402/);
  assert.equal((await post("/api/alert", { kind: "llm", code: "<b>x</b>" })).status, 200);
  assert.ok(!sent[1].text.includes("<b>"));
  assert.equal((await post("/api/alert", { kind: "constructor", text: "hi" })).status, 400);
  assert.equal(sent.length, 2);
});

test("the data tokens: a reminder 30 days before the last day, none on an ordinary day", async () => {
  await run("0 9 * * *", Date.UTC(2027, 8, 30, 9)); // 31 days left
  assert.equal(sent.length, 0);
  await run("0 9 * * *", Date.UTC(2027, 9, 1, 9)); // 30 days left
  assert.equal(sent.length, 1);
  assert.match(sent[0].text, /через 30 дн/);
  await run("0 9 * * *", Date.UTC(2027, 9, 2, 9));
  assert.equal(sent.length, 1);
});

test("/api/public is counted once in ten minutes; /api/mark takes only a review's id and a number", async () => {
  const score = (uid, s) => db.prepare("INSERT INTO marks (user_id, review_id, score, updated_at) VALUES (?,?,?,'t')").run(uid, "b", s);
  score(1, 6); score(2, 7); score(3, 8);
  const get = async () => (await worker.fetch(new Request("https://w/api/public"), env, { waitUntil() {} })).json();
  assert.deepEqual((await get()).avg.b, { avg: 7, many: false });
  db.prepare("UPDATE marks SET score=10").run();
  assert.deepEqual((await get()).avg.b, { avg: 7, many: false }); // the kept answer
  const kept = setting("public_stats");
  db.prepare("UPDATE settings SET value=? WHERE key='public_stats'").run(`${Date.now() - 601e3}|${kept.slice(kept.indexOf("|") + 1)}`);
  assert.deepEqual((await get()).avg.b, { avg: 10, many: false });

  // a session as the site holds it (login): id.exp.signature
  env.SESSION_SECRET = "s";
  const exp = Math.floor(Date.now() / 1000) + 60;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode("s"), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = [...new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`7.${exp}`)))].map((b) => b.toString(16).padStart(2, "0")).join("");
  const mark = (body) => worker.fetch(new Request("https://w/api/mark", { method: "POST", headers: { Authorization: `Bearer 7.${exp}.${sig}` }, body: JSON.stringify(body) }), env, { waitUntil() {} });
  assert.equal((await mark({ review_id: "x".repeat(200), status: "done" })).status, 400);
  assert.equal((await mark({ review_id: "a b", status: "done" })).status, 400);
  assert.equal((await mark({ review_id: "abc", score: "many" })).status, 400);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM marks WHERE user_id=7").get().n, 0);
  assert.equal((await mark({ review_id: "5f2c1e0a9b3d4c5e6f7a8b9c", status: "done", score: 8 })).status, 200);
  assert.equal(db.prepare("SELECT score FROM marks WHERE user_id=7").get().score, 8);
});
