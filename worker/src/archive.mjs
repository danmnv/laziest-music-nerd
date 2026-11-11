// The archive as the bot reads it: data/archive.min.json, a compact copy of data/archive.json made for the Worker
// (worker/tools/pack-archive.mjs writes it in the check workflow). Why: the free plan gives a Worker 10 ms of CPU per
// press, and reading archive.json cost three times that on a press that found no warm instance (Cloudflare's own
// numbers, 2026-11-10: P90 29.6 ms, P99 34.8 ms): parsing 3400 objects of 15 fields, then nameKey over every artist and
// album for a search. Here the fields are columns (one array per field: far fewer objects to parse), the search keys
// are counted ahead (ak, lk), genre tags are split only when a card or «похожие» asks for them, and the double posts
// are already left out (their ids are in alias).
import { nameKey } from "./follow.mjs";
import { dupAliases } from "./dups.mjs";

export const FORMAT = 1;
const COLUMNS = ["id", "artist_name", "album", "published", "url", "score", "video_id"]; // one array each, as they are
const FLAGS = ["classic", "not_good", "guest", "track"]; // true/false: one character per review (bits)
const UNUSED = ["tnd_published", "score_source", "artist_mbid", "dup_of"]; // the bot never reads these
const SEP = "|"; // between a review's genre tags

// A review's tags in lower case, for comparing them; counted once and kept.
export const tagKeys = (a) => (a.ks !== undefined ? a.ks : (a.ks = (a.genres || []).map((x) => String(x).toLowerCase())));

// For «похожие»: which reviews have any of these tags (wanted: a Set of lower-case tags).
// -> { df: {tag: how many times it occurs in the archive}, shared: [[review, its tags among the wanted]] }.
// The packed archive brings a ready list of reviews for every tag, so nothing is read but those lists; without it
// (archive.json itself) every review's tags are looked through.
export function sharedTags(got, wanted) {
  const df = {};
  if (!wanted.size) return { df, shared: [] };
  const t = got.tags;
  if (t) {
    if (!t.at) t.at = new Map(t.keys.map((k, i) => [k, i]));
    const by = new Map();
    for (const k of wanted) {
      const i = t.at.get(k);
      if (i === undefined) continue;
      const rows = t.rows[i].split(",");
      df[k] = rows.length;
      for (const j of rows) { const mine = by.get(j); if (mine) mine.push(k); else by.set(j, [k]); }
    }
    return { df, shared: [...by].sort((x, y) => x[0] - y[0]).map(([j, mine]) => [got.data[j], mine]) };
  }
  const shared = [];
  for (const a of got.data) {
    let mine = null;
    for (const k of tagKeys(a)) if (wanted.has(k)) { df[k] = (df[k] || 0) + 1; (mine ||= []).push(k); }
    if (mine) shared.push([a, mine]);
  }
  return { df, shared };
}

// Which of two strings comes first, by their characters: -1, 0 or 1 for sort(). Not localeCompare: its first call in
// a fresh instance loads the language tables (about 7 ms of the 10 a press may use), and what is sorted here are
// dates, years and ids, where the plain order is the same.
export const order = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// nameKey of the artist and of the album: counted ahead in the packed archive, counted once and kept otherwise
// (archive.json itself while there is no packed copy; reviews.json's cards)
export const artistKey = (a) => (a.ak !== undefined ? a.ak : (a.ak = nameKey(a.artist_name)));
export const albumKey = (a) => (a.lk !== undefined ? a.lk : (a.lk = nameKey(a.album)));

// archive.json's list -> the packed object (JSON.stringify it). Anything not known here travels in "x" by the
// review's index, so a field added to the archive later is not lost.
export function pack(raw) {
  const rows = (raw || []).filter((a) => a && !a.dup_of);
  const c = Object.fromEntries(COLUMNS.map((f) => [f, rows.map((a) => (a[f] === undefined ? null : a[f]))]));
  // nearly every review's address starts alike (https://theneedledrop.com/album-reviews/): that start is kept once (u)
  // and cut from the addresses that have it; any other address stays whole, known by its "://"
  const dir = (v) => v.slice(0, v.replace(/\/$/, "").lastIndexOf("/") + 1);
  const dirs = new Map();
  for (const v of c.url) if (typeof v === "string") dirs.set(dir(v), (dirs.get(dir(v)) || 0) + 1);
  const u = [...dirs].sort((p, q) => q[1] - p[1]).map(([d]) => d).find((d) => d.includes("://")) || "";
  if (u) c.url = c.url.map((v) => (typeof v === "string" && v.startsWith(u) && v.length > u.length && !v.slice(u.length).includes("://") ? v.slice(u.length) : v));
  c.ak = rows.map((a) => nameKey(a.artist_name));
  c.lk = rows.map((a) => nameKey(a.album));
  const plain = (a) => Array.isArray(a.genres) && a.genres.every((g) => typeof g === "string" && g && !g.includes(SEP));
  c.g = rows.map((a) => (plain(a) ? a.genres.join(SEP) : ""));
  c.fl = rows.map((a) => String.fromCharCode(48 + FLAGS.reduce((bits, f, i) => bits | (a[f] ? 1 << i : 0), 0))).join("");
  const known = new Set([...COLUMNS, ...FLAGS, ...UNUSED, "ak", "lk"]);
  const x = {};
  rows.forEach((a, i) => {
    const rest = Object.entries(a).filter(([k, v]) => !known.has(k) && v != null && v !== false && !(k === "genres" && (plain(a) || !a.genres.length)));
    if (rest.length) x[i] = Object.fromEntries(rest);
  });
  // every tag in lower case -> the reviews that have it, by index, once per occurrence (sharedTags)
  const where = new Map();
  rows.forEach((a, i) => { for (const g of a.genres || []) { const k = String(g).toLowerCase(); if (where.has(k)) where.get(k).push(i); else where.set(k, [i]); } });
  const t = { keys: [...where.keys()], rows: [...where.values()].map((list) => list.join(",")) };
  return { v: FORMAT, n: rows.length, alias: dupAliases(raw), u, c, x, t };
}

// One review. The same fields as in archive.json; genres are split from their string on first use.
class Row {
  constructor(c, i, u) {
    const bits = c.fl.charCodeAt(i) - 48;
    this.id = c.id[i];
    this.artist_name = c.artist_name[i];
    this.album = c.album[i];
    this.ak = c.ak[i];
    this.lk = c.lk[i];
    this.published = c.published[i];
    this.url = u && typeof c.url[i] === "string" && !c.url[i].includes("://") ? u + c.url[i] : c.url[i];
    this.score = c.score[i];
    this.video_id = c.video_id[i];
    this.classic = (bits & 1) !== 0;
    this.not_good = (bits & 2) !== 0;
    this.guest = (bits & 4) !== 0;
    this.track = (bits & 8) !== 0;
    this.g = c.g[i];
  }
  // split on first use and kept (gs); a plain field, not defineProperty: «похожие» asks every review for its tags
  get genres() {
    return this.gs !== undefined ? this.gs : (this.gs = this.g ? this.g.split(SEP) : []);
  }
  set genres(v) {
    this.gs = v;
  }
}

// The packed object -> { data: the reviews (double posts left out), alias: {double post's id: the first post's},
// tags: the reviews of every tag (sharedTags) },
// or null when it isn't a packed archive of this format (the caller reads archive.json then).
export function unpack(d) {
  const c = d && d.c;
  if (!d || d.v !== FORMAT || !c || typeof c.fl !== "string" || c.fl.length !== d.n) return null;
  if ([...COLUMNS, "ak", "lk", "g"].some((f) => !Array.isArray(c[f]) || c[f].length !== d.n)) return null;
  const data = new Array(d.n);
  const u = typeof d.u === "string" ? d.u : "";
  for (let i = 0; i < d.n; i++) data[i] = new Row(c, i, u);
  for (const [i, rest] of Object.entries(d.x || {})) if (data[i]) Object.assign(data[i], rest);
  const t = d.t && Array.isArray(d.t.keys) && Array.isArray(d.t.rows) && d.t.keys.length === d.t.rows.length ? { keys: d.t.keys, rows: d.t.rows } : null;
  return { data, alias: d.alias || {}, tags: t };
}

// archive.json's list as the bot uses it, when there is no packed copy
export function plain(raw) {
  return { data: (raw || []).filter((a) => !a.dup_of), alias: dupAliases(raw), tags: null };
}
