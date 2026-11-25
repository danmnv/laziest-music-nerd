import manifest from "../../lmn/decade_tens_manifest.json" with { type: "json" };
import { albumKey, artistKey, order } from "./archive.mjs";
import { nameKey } from "./follow.mjs";

export const DECADE_PREFIX = manifest.prefix;

const newer = (a, b) => order(String(b.published), String(a.published));
const releaseKey = (a) => `${artistKey(a)}|${albumKey(a)}`;
const episodeById = new Map();
const episodeByName = new Map();
const decades = new Map();

for (const [video, [decade, published, albums]] of Object.entries(manifest.episodes)) {
  const entries = [];
  decades.set(decade, entries);
  for (const [key, artist, title, genre] of albums) {
    const id = DECADE_PREFIX + key;
    const review = { id, artist_name: artist, album: title, genres: [genre], published, url: `https://youtu.be/${video}`, score: 10 };
    entries.push(review);
    episodeById.set(id, review);
    for (const [a, t] of [[artist, title], ...(manifest.aliases[key] || [])]) {
      episodeByName.set(`${nameKey(a)}|${nameKey(t)}`, id);
    }
  }
}

export const episodeReview = (id) => episodeById.get(id);
const isReview = (a) => a.artist_name && a.album && !a.track && !a.dup_of && !a.non_review && !a.redo;

export function tenReviews(archive) {
  const originals = [];
  const existing = new Map();
  for (const a of archive) {
    if (!isReview(a) || a.guest) continue;
    const episodeOnly = a.id.startsWith(DECADE_PREFIX);
    if (!episodeOnly && a.score === 10 && !a.classic && !a.not_good) originals.push(a);

    const episode = episodeOnly ? a.id : episodeByName.get(releaseKey(a));
    const previous = existing.get(episode);
    if (episode && (!previous || (!episodeOnly && previous.id.startsWith(DECADE_PREFIX)) ||
      (episodeOnly === previous.id.startsWith(DECADE_PREFIX) && newer(a, previous) < 0))) {
      existing.set(episode, a);
    }
  }

  const seen = new Set();
  const reviews = originals.sort(newer).filter((a) => {
    const key = episodeByName.get(releaseKey(a)) || releaseKey(a);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return {
    reviews,
    episodes: [...decades].map(([decade, rows]) => [
      decade, rows.filter((a) => !seen.has(a.id)).map((a) => existing.get(a.id) || a),
    ]),
  };
}

export function classicReviews(archive) {
  return archive.filter((a) => isReview(a) && a.classic && !a.not_good).sort(newer);
}
