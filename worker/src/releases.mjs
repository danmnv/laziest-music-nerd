// New albums of followed artists, sent before Fantano's review (owner, 2026-11-02). Pure helpers; index.js does the
// requests: Deezer's list of the artist's albums once a day per artist, a few artists per hourly run.
import { nameKey } from "./follow.mjs";

export const FRESH_DAYS = 14; // an album older than this when first seen came to Deezer late: remembered, not announced
export const RECHECK_HOURS = 20; // each followed artist about once a day

// "Kid A (Remastered)" -> "Kid A"; only a trailing bracket group goes, so "(What's the Story) Morning Glory?" stays whole
export const untitled = (t) => String(t || "").replace(/^["“]|["”]$/g, "").replace(/\s*[([][^)\]]*[)\]]\s*$/, "");

// Re-releases and side versions: not a new album (the owner gets albums and EPs, no spam)
const NOT_NEW = /\b(deluxe|remaster(ed)?|anniversary|expanded|edition|reissue|live (at|from|in)|instrumentals?|remix(es)?|demos|sped up|slowed)\b/i;

// The channel's quiet hours, 01:00–09:00 Moscow: nothing is sent then, it waits for the morning.
export function quietHour(date) {
  const h = date.getUTCHours();
  return h >= 22 || h < 6;
}

const day = (date) => date.toISOString().slice(0, 10);

// albums: Deezer's list of the artist's albums; seen: Deezer IDs known before (null on the first check).
// -> { fresh: albums to announce, seen: the IDs to remember }. The first check only remembers. An album dated after
// today isn't remembered yet, so it is announced on its day.
export function sortOut(albums, seen, today) {
  const known = new Set(seen || []);
  const next = [...known];
  const oldTitles = new Set(albums.filter((a) => known.has(a.id)).map((a) => nameKey(untitled(a.title))));
  const to = day(today);
  const from = day(new Date(today.getTime() - FRESH_DAYS * 864e5));
  const fresh = [];
  for (const a of albums) {
    const d = String(a.release_date || "");
    if (!a.id || known.has(a.id) || !/^\d{4}-\d\d-\d\d$/.test(d) || d > to) continue;
    next.push(a.id);
    known.add(a.id);
    if (!seen) continue;
    if (a.record_type !== "album" && a.record_type !== "ep") continue; // singles and compilations: not announced
    if (d < from || NOT_NEW.test(a.title || "") || oldTitles.has(nameKey(untitled(a.title)))) continue;
    fresh.push(a);
  }
  return { fresh, seen: next };
}

const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

// "2026-10-31" -> "31 октября"
export function ruDate(iso) {
  const m = /^\d{4}-(\d\d)-(\d\d)$/.exec(String(iso || ""));
  return m ? `${Number(m[2])} ${MONTHS[Number(m[1]) - 1]}` : "";
}
