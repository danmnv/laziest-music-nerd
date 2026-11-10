// /api/public is open to anyone: no album below 3 people, and no exact counts (owner, 2026-11-02).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/index.js";

function d1(sqlite) {
  return {
    prepare(sql) {
      let args = [];
      const st = { bind(...a) { args = a; return st; }, async all() { return { results: sqlite.prepare(sql).all(...args) }; },
        async first() { return sqlite.prepare(sql).get(...args) ?? null; }, async run() { sqlite.prepare(sql).run(...args); return {}; } };
      return st;
    },
  };
}

async function stats(fill) {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  fill(db);
  const r = await worker.fetch(new Request("https://w/api/public"), { DB: d1(db), SITE_URL: "https://site" }, { waitUntil() {} });
  return r.json();
}

const score = (db, uid, rid, s) => db.prepare("INSERT INTO marks (user_id, review_id, score, updated_at) VALUES (?,?,?,'t')").run(uid, rid, s);
const vote = (db, uid, rid, mood, v) => db.prepare("INSERT INTO mood_votes (user_id, review_id, mood, vote) VALUES (?,?,?,?)").run(uid, rid, mood, v);

test("scores: hidden below 3 people, then the average and only 'many or not'", async () => {
  const d = await stats((db) => {
    score(db, 1, "a", 7); score(db, 2, "a", 8);
    score(db, 1, "b", 6); score(db, 2, "b", 7); score(db, 3, "b", 8);
    for (let u = 1; u <= 10; u++) score(db, u, "c", 9);
  });
  assert.equal(d.avg.a, undefined);
  assert.deepEqual(d.avg.b, { avg: 7, many: false });
  assert.deepEqual(d.avg.c, { avg: 9, many: true });
  assert.ok(!JSON.stringify(d).includes('"n"'));
});

test("vibes: hidden below 3 voters; no counts, old words merged, retired words dropped", async () => {
  const d = await stats((db) => {
    vote(db, 1, "a", "для тренировки", "y"); vote(db, 2, "a", "для тренировки", "y");
    vote(db, 1, "b", "фоном", "y"); vote(db, 2, "b", "для работы за столом", "y"); vote(db, 3, "b", "фоном для работы", "n");
    vote(db, 3, "b", "для тусовки", "n"); vote(db, 1, "b", "ночью", "y");
  });
  assert.equal(d.moods.a, undefined);
  assert.deepEqual(d.moods.b, { many: false, list: [{ m: "фоном для работы", ok: true, bar: 100 }, { m: "для тусовки", ok: false, bar: 0 }] });
});
