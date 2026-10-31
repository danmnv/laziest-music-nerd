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
