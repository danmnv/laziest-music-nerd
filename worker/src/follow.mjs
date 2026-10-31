// Following an artist: who gets a private message when a new review of that artist comes out.
// An artist is matched by MusicBrainz ID when both the follow and the review have one, otherwise by name
// (MusicBrainz may not know a new artist yet, or know them only later).

export function nameKey(name) {
  const s = String(name || "");
  // fast path for plain ASCII (most names): search runs this over the whole archive on every query
  if (!/[^\x00-\x7f]/.test(s)) return s.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, "");
  return s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase()
    .replace(/&/g, "and").replace(/[^\p{L}\p{N}]+/gu, "");
}

export function followMatches(follow, artist) {
  if (follow.mbid && artist.mbid) return follow.mbid === artist.mbid;
  const key = nameKey(artist.artist_name);
  return Boolean(key) && follow.name_key === key;
}
