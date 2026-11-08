// Albums Fantano didn't review, from the owner's second AOTY table (lmn/aoty_top.py, 2026-11-08): genres, AOTY's score,
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
