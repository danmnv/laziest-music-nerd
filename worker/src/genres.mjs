// TND's tags mix genres with labels, places, people and site words ("music", "vlog", "atlantic"). A tag counts as a genre
// when it has a genre word from genres.json (shared with lmn/tnd.py). The tags in data/ stay as they are; this filters
// them when they are shown or compared.
import G from "./genres.json" with { type: "json" };

const WORD = new RegExp("\\b(" + G.words.join("|") + ")\\b", "i");
const NOT = new Set(G.not);

export function isGenre(tag) {
  const t = String(tag || "").trim().toLowerCase();
  return !NOT.has(t) && WORD.test(t);
}

export const genresOf = (a) => ((a && a.genres) || []).filter(isGenre);
