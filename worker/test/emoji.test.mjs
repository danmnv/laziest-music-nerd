import { test } from "node:test";
import assert from "node:assert/strict";
import { EMOJI, ce, plainEmoji } from "../src/emoji.mjs";

test("custom emoji tag, and plain when switched off", () => {
  assert.equal(ce({}, "banger"), '<tg-emoji emoji-id="5427076385522887347">🤘</tg-emoji>');
  assert.equal(ce({ CUSTOM_EMOJI: "0" }, "banger"), "🤘");
});

test("plainEmoji keeps the ordinary emoji and the rest of the text", () => {
  const html = `<b>Готово</b> ${ce({}, "banger")} и ${ce({}, "facepalm")}`;
  assert.equal(plainEmoji(html), "<b>Готово</b> 🤘 и 🤦‍♂️");
  assert.equal(plainEmoji("без эмодзи"), "без эмодзи");
});

test("every id is numeric and unique", () => {
  const ids = Object.values(EMOJI).map(([id]) => id);
  assert.ok(ids.every((id) => /^\d+$/.test(id)));
  assert.equal(new Set(ids).size, ids.length);
});
