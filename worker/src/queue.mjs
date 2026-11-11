// «Дослушать»: the reviews that came out after the last one a person has heard, oldest first, a page at a time
// (owner, 2026-11-01). Pure functions over archive.json and the person's marks; the Telegram side is in index.js.
import { genresOf } from "./genres.mjs";
import { badge } from "./search.mjs";
import { order } from "./archive.mjs";

export const PAGE = 15; // a page of the list: short enough to read on a phone, "Дальше" for the rest
export const OLD_DAYS = 365; // a starting point older than this is confirmed first: the list would be long
export const QFROM_MINUTES = 10; // «после какого альбома?» waits this long for its answer, then typing is a search again

const time = (a) => Date.parse(a.published) || 0;
const byTime = (x, y) => time(x) - time(y) || order(String(x.id), String(y.id));

// The last review heard: of the reviews marked «✓ Слушал» or «✗ Не моё» (both mean listened to), the one published
// last, not the one marked last. A 2015 album opened at random after the 2025 ones doesn't move the start back.
export function lastHeard(archive, statuses) {
  let best = null;
  for (const a of archive) {
    const s = statuses[a.id];
    if ((s === "done" || s === "nope") && (!best || byTime(a, best) > 0)) best = a;
  }
  return best;
}

// Every review published after this one, oldest first.
export function after(archive, from) {
  return archive.filter((a) => byTime(a, from) > 0).sort(byTime);
}

// The review published just before this one, heard or not: «← Назад» on a «Наверстать» card (owner, 2026-11-02);
// null for the oldest review.
export function before(archive, from) {
  let best = null;
  for (const a of archive) if (byTime(a, from) < 0 && (!best || byTime(a, best) > 0)) best = a;
  return best;
}

// The next review to hear after this one, skipping the ones already marked heard and the ones put off for later
// (they are in the «Послушать потом» block at the top instead); null at the end.
export function nextAfter(archive, from, statuses) {
  return after(archive, from).find((a) => !statuses[a.id]) || null;
}

// The «Послушать потом» block at the top of «Наверстать» (owner, 2026-11-02: «отложенные всегда должны быть в топе
// наверстать»; «самые старые отложенные первыми, самые свеже отложенные последние»): the reviews among these IDs, in
// their order. Albums without a review aren't in the block.
export function laterReviews(archive, ids) {
  const byId = new Map(archive.map((a) => [a.id, a]));
  return ids.map((id) => byId.get(id)).filter(Boolean);
}

export function daysOld(a, now = Date.now()) {
  return Math.floor((now - time(a)) / 864e5);
}

// One line as in the channel's pinned list: badge · Artist — Album (a link that opens the card in this mode) · genre ·
// the review's date, so the person sees where in time they are.
export function line(a, link, esc, status = "") {
  const genre = genresOf(a)[0];
  const date = String(a.published).slice(0, 10).split("-").reverse().join(".");
  return `${badge(a)} · <a href="${link}">${esc(a.artist_name)} — ${esc(a.album)}</a>${genre ? " · " + esc(genre) : ""} · ${date}${status}`;
}
