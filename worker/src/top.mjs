// Albums Fantano didn't review, from the owner's second music-database table (lmn/aoty_top.py, 2026-11-08): genres, AOTY's score,
// a few critics, the tracklist and album links, in the site's u/<shard>.json. The key and shard as in lmn/aoty_top.py.
import { nameKey } from "./follow.mjs";
import { untitled } from "./releases.mjs";

export function topKey(artist, title) {
  return `${nameKey(artist).slice(0, 60)}--${nameKey(untitled(title)).slice(0, 80)}`;
}

export function topShard(k) {
  const s = k.slice(0, 2);
  return /^[a-z0-9-]{2}$/.test(s) ? s : "__";
}

// The critics line of a card: up to 3 outlets, then AOTY's score (owner, 2026-11-03: shown like Metacritic)
export function topCritics(e) {
  if (!e) return [];
  const out = (e.c || []).slice(0, 3).map(([o, s]) => `${o} ${s}`);
  if (e.s != null) out.push(`AOTY ${e.s}/100`);
  return out;
}

export async function topAlbum(siteUrl, artist, title, get = fetch) {
  const k = topKey(artist, title);
  if (!siteUrl || k.startsWith("--") && k.endsWith("--")) return null;
  try {
    const r = await get(`${siteUrl}/u/${topShard(k)}.json`, { cf: { cacheTtl: 86400 } });
    return r.ok ? (await r.json())[k] || null : null;
  } catch {
    return null;
  }
}

// A small index of releases that share a title or cannot use the regular key.
// Its IDs come from the supplied table and stay stable when titles are edited.
export async function loadVariants(siteUrl, get = fetch) {
  if (!siteUrl) return {};
  try {
    const r = await get(`${siteUrl}/av.json`, { cf: { cacheTtlByStatus: { "200-299": 3600, "404": 60 } } });
    return r.ok ? await r.json() : {};
  } catch {
    return {};
  }
}

// Preserve names such as "!!!", "( )" and "†" when there are no letters.
export const fullName = (s) => nameKey(s) || String(s || "").normalize("NFKC").toLowerCase().replace(/\s+/gu, "");
export const variantYear = (e) => String(e.d || "").slice(0, 4);
const fullTitles = (e) => [e.t, ...(e.aliases || [])].map(fullName);
const titleSuffix = (t) => t.match(/\s+[([]([^()[\]]+)[)\]]$/u)?.[1];

export function searchVariants(variants, query) {
  const dated = /^(.+?)\s+\(?(\d{4})\)?$/u.exec(query);
  const wanted = fullName(dated ? dated[1] : query);
  if (!wanted) return [];
  return Object.entries(variants).filter(([, e]) => {
    if (dated && variantYear(e) !== dated[2]) return false;
    const artist = fullName(e.a);
    const titles = [...fullTitles(e), nameKey(untitled(e.t))].filter(Boolean);
    const suffix = titleSuffix(e.t);
    return wanted === artist || titles.some((t) => wanted === t || wanted === artist + t) ||
      (suffix && (wanted === fullName(suffix) || wanted === artist + fullName(suffix)));
  });
}

export function variantsOf(variants, artist, title) {
  const name = fullName(artist);
  const full = fullName(title);
  const bare = nameKey(untitled(title));
  return Object.entries(variants).filter(([, e]) => fullName(e.a) === name &&
    (!title || fullTitles(e).includes(full) || (bare && bare === nameKey(untitled(e.t)))));
}

export function matchVariant(editions, title, year) {
  const full = fullName(title);
  const dated = year ? editions.filter(([, e]) => variantYear(e) === year) : editions;
  const exact = dated.filter(([, e]) => fullTitles(e).includes(full));
  const qualified = titleSuffix(title);
  if (exact.length === 1 && (year || qualified || !nameKey(untitled(title)))) return exact[0];
  return year && !qualified && exact.length === 0 && dated.length === 1 ? dated[0] : null;
}
