// Matching an album in Deezer's search results to a review (the same rules as lmn/links.py find_album).
import { nameKey } from "./follow.mjs";

// The names an album may be credited to on Deezer: the full name first, then each artist of a collaboration
// ("Nas & DJ Premier" is an album of "Nas" there). The parts only count when the full name finds nothing.
export function creditedNames(artist) {
  const parts = String(artist || "").split(/\s*(?:&|,|\+|\||\bx\b|\bwith\b|\bfeat\.?|\band\b)\s*/i).map((x) => x.trim()).filter(Boolean);
  return [artist, ...(parts.length > 1 ? parts : [])];
}

// Fantano writes "Self-Titled" where the album is called after the artist ("Megadeth — Self-Titled").
export function selfTitled(artist, album) {
  const m = /^self[- ]?titled\b(.*)$/i.exec(String(album || "").trim());
  return m ? `${artist}${m[1]}` : album;
}

// A release nickname in brackets is part of its name. A remaster or deluxe suffix may be omitted.
export function albumTitleKey(title) {
  return nameKey(String(title || "").replace(/\(the\s+(?=[^\s()]+\s+album\))/gi, "("));
}

export function albumTitleMatches(title, want) {
  const base = String(title || "").replace(/\s*[\[(](?:(?:\d{4}\s+)?(?:digitally\s+)?remaster(?:ed)?|(?:super\s+)?deluxe|expanded|(?:\d+(?:st|nd|rd|th)\s+)?anniversary|special|bonus(?:\s+track)?)(?:\s+edition)?[\])]\s*$/i, "");
  return Boolean(want) && (albumTitleKey(title) === want || albumTitleKey(base) === want);
}

export function pickAlbum(results, names, album) {
  const want = albumTitleKey(album);
  const keys = names.map(nameKey).filter(Boolean);
  // a single named after the album comes first in the search for some (KNEECAP "FENIAN", 2026-11-08: a 3-track single
  // with its own cover): the album itself first, then the exact title, then the longest (lmn/links.py _rank)
  const rank = (x) => [x.record_type !== "single" ? 1 : 0, albumTitleKey(x.title) === want ? 1 : 0, x.nb_tracks || 0];
  const better = (a, b) => { const [p, q] = [rank(a), rank(b)]; for (let i = 0; i < 3; i++) if (p[i] !== q[i]) return p[i] > q[i]; return false; };
  for (const k of keys) {
    const hits = (results || []).filter((x) => x && x.artist && nameKey(x.artist.name) === k && albumTitleMatches(x.title, want));
    if (hits.length) return hits.reduce((a, b) => (better(b, a) ? b : a));
  }
  return null;
}
