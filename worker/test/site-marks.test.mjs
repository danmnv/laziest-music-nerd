// Run the release page's real app.js against a minimal DOM and fake responses.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { test } from "node:test";

const app = readFileSync(new URL("../../site_src/app.js", import.meta.url), "utf8");
const reply = (body, status = 200) => Response.json(body, { status });

async function page(write) {
  const status = { dataset: { s: "done" } }, score = {}, feedback = {};
  const box = {
    querySelectorAll: () => [status],
    querySelector: (selector) => selector === "#myscore" ? score : feedback,
  };
  const release = { dataset: { id: "r1" }, querySelector: () => box, querySelectorAll: () => [] };
  const login = { nodes: [], replaceChildren() { this.nodes = []; }, appendChild(node) { this.nodes.push(node); } };
  const store = new Map([["lmn_token", "tok"]]);
  const localStorage = { getItem: (key) => store.get(key), removeItem: (key) => store.delete(key) };
  const document = {
    getElementById: (id) => ({ login, logout: {} })[id],
    querySelector: () => release,
    querySelectorAll: () => [],
    createElement: () => ({ dataset: {} }),
  };
  let attempts = 0;
  const fetch = (url, opts) => {
    if (url.endsWith("/api/public")) return reply({});
    if (url.endsWith("/api/me/marks")) return reply({ marks: { r1: { score: 5 } } });
    assert.ok(url.endsWith("/api/mark"), url);
    attempts++;
    return write(opts);
  };
  runInNewContext(app, { window: { LMN: { worker: "https://w", root: "/" } }, document, localStorage, fetch, navigator: {} });
  await new Promise(setImmediate);
  return { status, score, feedback, store, box, login, attempts: () => attempts };
}

test("expired login shows the Telegram login again and leaves the requested mark unapplied", async () => {
  const p = await page(() => reply({ error: "login" }, 401));
  await p.status.onclick();
  assert.equal(p.status.className, "btn");
  assert.equal(p.store.has("lmn_token"), false);
  assert.match(p.box.textContent, /Вход истёк/);
  assert.match(p.login.nodes[0].src, /telegram-widget/);
});

test("neither server nor network errors change the last confirmed mark or score", async () => {
  const p = await page((opts) => {
    if ("score" in JSON.parse(opts.body)) throw new TypeError("network unavailable");
    return reply({ error: "server" }, 500);
  });
  await p.status.onclick();
  assert.equal(p.status.className, "btn");
  assert.match(p.feedback.textContent, /Попробуй ещё раз/);
  p.score.value = "8";
  await p.score.onchange();
  assert.equal(p.score.value, 5);
  assert.equal(p.score.disabled, false);
  assert.match(p.feedback.textContent, /Попробуй ещё раз/);
});

test("a successful response is required and extra clicks wait while the request is in flight", async () => {
  const confirm = Promise.withResolvers();
  const score = Promise.withResolvers();
  const p = await page((opts) => ("score" in JSON.parse(opts.body) ? score.promise : confirm.promise));
  const save = p.status.onclick();
  assert.equal(p.status.disabled, true);
  assert.equal(p.status.className, "btn");
  await p.status.onclick();
  assert.equal(p.attempts(), 1);
  confirm.resolve(reply({ ok: true }));
  await save;
  assert.equal(p.status.className, "btn on");
  p.score.value = "8";
  const rate = p.score.onchange();
  score.resolve(reply({ ok: false }));
  await rate;
  assert.equal(p.score.value, 5);
  assert.match(p.feedback.textContent, /Попробуй ещё раз/);
});
