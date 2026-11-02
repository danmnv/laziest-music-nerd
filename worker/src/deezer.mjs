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

// The result for this album: the same title ("Kid A (Remastered)" counts as "Kid A", "Muddy" doesn't as "Mud"),
// by the full artist name first, then by one of the credited names.
export function pickAlbum(results, names, album) {
  const want = nameKey(album);
  const same = (x) => nameKey(x.title) === want || nameKey(String(x.title || "").replace(/\s*[([].*$/, "")) === want;
  const keys = names.map(nameKey).filter(Boolean);
  for (const k of keys) {
    const hit = (results || []).find((x) => x && x.artist && nameKey(x.artist.name) === k && same(x));
    if (hit) return hit;
  }
  return null;
}
