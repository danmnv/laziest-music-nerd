import { test } from "node:test";
import assert from "node:assert/strict";
import { creditedNames, selfTitled, pickAlbum } from "../src/deezer.mjs";

const r = (id, title, artist) => ({ id, title, artist: { name: artist } });

test("the title matches without its punctuation and accents, and only for the same artist", () => {
  const names = creditedNames("Angine de Poitrine");
  assert.equal(pickAlbum([r(1, "Vol.1", "Angine de Poitrine"), r(2, "Vol.II", "Angine de Poitrine")], names, "Vol. II").id, 2);
  assert.equal(pickAlbum([r(3, "Skeletá", "Ghost")], creditedNames("Ghost"), "Skeletá").id, 3);
  assert.equal(pickAlbum([r(4, "Kid A (Remastered)", "Radiohead")], ["Radiohead"], "Kid A").id, 4);
  assert.equal(pickAlbum([r(5, "The Life of a Showgirl", "Minnz Piano")], ["Taylor Swift"], "The Life of a Showgirl"), null);
  assert.equal(pickAlbum([r(6, "Muddy", "X")], ["X"], "Mud"), null);
});

test("a collaboration is found under one of its artists, the full name first", () => {
  assert.deepEqual(creditedNames("Nas & DJ Premier"), ["Nas & DJ Premier", "Nas", "DJ Premier"]);
  assert.deepEqual(creditedNames("Radiohead"), ["Radiohead"]);
  const names = creditedNames("Simon & Garfunkel");
  assert.equal(pickAlbum([r(7, "Bookends", "Simon"), r(8, "Bookends", "Simon & Garfunkel")], names, "Bookends").id, 8);
  assert.equal(pickAlbum([r(9, "Light-Years", "Nas")], creditedNames("Nas & DJ Premier"), "Light-Years").id, 9);
});

test("Fantano's Self-Titled is the artist's name", () => {
  assert.equal(selfTitled("Megadeth", "Self-Titled"), "Megadeth");
  assert.equal(selfTitled("Weezer", "Self-Titled (Gold)"), "Weezer (Gold)");
  assert.equal(selfTitled("X", "Vol. II"), "Vol. II");
});
