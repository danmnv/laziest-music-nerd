import { test } from "node:test";
import assert from "node:assert/strict";
import { dupAliases, remapStatements, DUP_TABLES } from "../src/dups.mjs";

test("dup ids map to the first post", () => {
  assert.deepEqual(dupAliases([{ id: "a" }, { id: "b", dup_of: "a" }, { id: "c" }]), { b: "a" });
  assert.deepEqual(dupAliases(null), {});
});

test("every table gets a move and a clean-up per dup", () => {
  const s = remapStatements({ b: "a" });
  assert.equal(s.length, DUP_TABLES.length * 2 + 1);
  assert.deepEqual(s[0], ["UPDATE OR IGNORE marks SET review_id=? WHERE review_id=?", ["a", "b"]]);
  assert.deepEqual(s[1], ["DELETE FROM marks WHERE review_id=?", ["b"]]);
  assert.deepEqual(s.at(-1), ["UPDATE settings SET value=? WHERE key LIKE 'qpos:%' AND value=?", ["a", "b"]]);
  assert.deepEqual(remapStatements({}), []);
});
