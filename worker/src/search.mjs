// Search Fantano's reviews (archive.json) by artist and album, for the private chat with the bot.
import { nameKey } from "./follow.mjs";

// Every word of the query must appear in the artist or album name ("kid a radiohead" finds Radiohead — Kid A).
// Ranked: the artist named exactly, then artists starting with the query, then the rest; newest first within each.
export function searchArchive(archive, query, limit = 8) {
  const words = String(query || "").split(/\s+/).map(nameKey).filter(Boolean);
  if (!words.length) return { total: 0, items: [] };
  const whole = words.join("");
  const hits = [];
  for (const a of archive) {
    if (!a.artist_name && !a.album) continue;
    const artist = nameKey(a.artist_name), hay = artist + "|" + nameKey(a.album);
    if (!words.every((w) => hay.includes(w))) continue;
    hits.push({ a, rank: artist === whole ? 0 : artist.startsWith(whole) ? 1 : 2 });
  }
  hits.sort((x, y) => x.rank - y.rank || String(y.a.published).localeCompare(String(x.a.published)));
  return { total: hits.length, items: hits.slice(0, limit).map((h) => h.a) };
}

// "🟢 8/10", "🔴 NOT GOOD", "⚪ без оценки" (the 2010-2014 reviews often have no score in the data).
export function badge(a) {
  if (a.not_good) return "🔴 NOT GOOD";
  if (a.classic) return "🟢 CLASSIC";
  if (a.score == null) return "⚪ без оценки";
  return `${a.score >= 8 ? "🟢" : a.score >= 5 ? "🟡" : "🔴"} ${a.score}/10`;
}

// What to answer a search with:
// - "none"; "card" for a single review;
// - "albums": one artist's reviews (the artist named exactly, or the only artist found), or a few hits of mixed artists;
// - "artists": many hits across artists, so pick the artist first.
export function answerSearch(archive, query, { maxAlbums = 40, fewHits = 8, maxArtists = 10 } = {}) {
  const { total, items } = searchArchive(archive, query, Infinity);
  if (!total) return { kind: "none" };
  if (total === 1) return { kind: "card", item: items[0] };
  const groups = new Map();
  for (const a of items) {
    const k = nameKey(a.artist_name);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(a);
  }
  const exact = groups.get(String(query || "").split(/\s+/).map(nameKey).join(""));
  if (exact || groups.size === 1) {
    const mine = exact || items;
    return { kind: "albums", artist: mine[0].artist_name, total: mine.length, items: mine.slice(0, maxAlbums), others: total - mine.length };
  }
  if (total <= fewHits) return { kind: "albums", artist: null, total, items, others: 0 };
  const artists = [...groups.values()].sort((x, y) => y.length - x.length).slice(0, maxArtists)
    .map((g) => ({ name: g[0].artist_name, count: g.length, id: g[0].id }));
  return { kind: "artists", total, artists, groups: groups.size };
}

// All reviews of the artist of review `id`, newest first.
export function artistReviews(archive, id, max = 40) {
  const a = archive.find((x) => x.id === id);
  if (!a) return { artist: null, total: 0, items: [] };
  const k = nameKey(a.artist_name);
  const items = archive.filter((x) => nameKey(x.artist_name) === k)
    .sort((x, y) => String(y.published).localeCompare(String(x.published)));
  return { artist: a.artist_name, total: items.length, items: items.slice(0, max) };
}
