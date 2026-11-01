// Critic scores and chart peaks for an album Fantano never reviewed, read on demand from its English Wikipedia
// article. A port of the parts of lmn/ratings.py the bot's card needs (reviewed albums come from data/ratings.json
// through the site's rt/<id>.json instead). Output has the shape critics.mjs prints: { crit, sales, wp_url }.

const WP_API = "https://en.wikipedia.org/w/api.php";
const UA = "LaziestMusicNerd/1.0 (https://github.com/danmnv/laziest-music-nerd)";

// Same order and aliases as lmn/ratings.py.
const PRIORITY = ["Pitchfork", "AllMusic", "NME", "Rolling Stone", "The Guardian", "Clash", "Exclaim!", "The A.V. Club",
  "Spin", "The Independent", "The Line of Best Fit", "Paste", "Uncut", "Mojo", "Entertainment Weekly",
  "Slant Magazine", "Consequence", "PopMatters", "The Observer", "musicOMH", "DIY", "HipHopDX", "XXL",
  "Beats Per Minute", "Kerrang!", "Metal Hammer", "The Quietus", "Resident Advisor", "Under the Radar",
  "The Daily Telegraph", "The Times", "Q", "Record Collector", "Sputnikmusic"];
const ALIASES = { "pitchfork media": "Pitchfork", "consequence of sound": "Consequence", "slant": "Slant Magazine",
  "the av club": "The A.V. Club", "a.v. club": "The A.V. Club", "the guardian": "The Guardian", "guardian": "The Guardian",
  "the telegraph": "The Daily Telegraph", "allmusic": "AllMusic", "nme": "NME", "musicomh": "musicOMH" };
const CHARTS = { billboard200: "US", uk2: "UK" };
const REGIONS = { "united states": "US", "united kingdom": "UK", "canada": "CA", "australia": "AU", "germany": "DE",
  "france": "FR", "japan": "JP" };
const GRADES = { "A+": 10, "A": 9.5, "A−": 9, "A-": 9, "B+": 8.5, "B": 8, "B−": 7.5, "B-": 7.5, "C+": 7, "C": 6.5,
  "C−": 6, "C-": 6, "D+": 5, "D": 4, "D−": 3, "D-": 3, "E": 2, "F": 1 };

export function norm(s) {
  return String(s || "").replace(/\$/g, "s").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/&/g, "and").replace(/[^a-z0-9]/g, "");
}

// First {{name ...}} template with balanced braces, or null.
export function template(text, names) {
  const low = text.toLowerCase();
  let best = -1;
  for (const n of names) {
    const re = new RegExp("\\{\\{\\s*" + n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "[ _]") + "\\s*[|}]");
    const m = re.exec(low);
    if (m && (best < 0 || m.index < best)) best = m.index;
  }
  if (best < 0) return null;
  let depth = 0;
  for (let j = best; j < text.length - 1;) {
    const two = text.slice(j, j + 2);
    if (two === "{{") { depth++; j += 2; } else if (two === "}}") { depth--; j += 2; if (!depth) return text.slice(best, j); } else j++;
  }
  return null;
}

export function params(t) {
  const body = t.slice(2, -2);
  const parts = [];
  let depth = 0, cur = "";
  for (let i = 0; i < body.length;) {
    const two = body.slice(i, i + 2);
    if (two === "{{" || two === "[[") { depth++; cur += two; i += 2; } else if (two === "}}" || two === "]]") { depth--; cur += two; i += 2; } else if (body[i] === "|" && !depth) { parts.push(cur); cur = ""; i++; } else { cur += body[i]; i++; }
  }
  parts.push(cur);
  const out = {};
  let pos = 0;
  for (const p of parts.slice(1)) {
    const eq = p.indexOf("=");
    if (eq >= 0 && /^\s*[\w ?-]+\s*$/.test(p.slice(0, eq))) out[p.slice(0, eq).trim().toLowerCase()] = p.slice(eq + 1).trim();
    else out[String(++pos)] = p.trim();
  }
  return out;
}

const fmt = (x) => String(Number.isInteger(x) ? x : x);

export function clean(v) {
  v = String(v || "").replace(/<ref[^>]*\/>/g, "").replace(/<ref[\s\S]*?<\/ref>/g, "").replace(/<!--[\s\S]*?-->/g, "");
  const m = /\{\{\s*rating\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)/i.exec(v);
  if (m) return `${fmt(parseFloat(m[1]))}/${fmt(parseFloat(m[2]))}`;
  v = v.replace(/\[\[(?:[^|\]]*\|)?([^\]]*)\]\]/g, "$1").replace(/\[https?:\/\/\S+\s+([^\]]*)\]/g, "$1")
    .replace(/\{\{[^{}]*\}\}/g, "").replace(/'''/g, "").replace(/''/g, "");
  return v.replace(/\s+/g, " ").trim().replace(/^[\s()]+|[\s()]+$/g, "");
}

function outletName(raw) {
  const name = clean(raw);
  const key = name.toLowerCase().trim();
  return ALIASES[key] || PRIORITY.find((p) => p.toLowerCase() === key) || name;
}

function to10(score) {
  const s = score.replace(/,/g, ".").trim();
  let m = /^([\d.]+)\s*%$/.exec(s);
  if (m) return parseFloat(m[1]) <= 100 ? Math.round(parseFloat(m[1])) / 10 : null;
  m = /^([\d.]+)\s*\/\s*([\d.]+)$/.exec(s);
  if (m) { const a = parseFloat(m[1]), b = parseFloat(m[2]); return b && a <= b ? Math.round(100 * a / b) / 10 : null; }
  return s in GRADES ? GRADES[s] : null;
}

// The lines a card shows, from one article's wikitext: up to 5 known critics with real scores, Metacritic, chart peaks.
export function parse(text) {
  const crit = [], sales = [];
  const box = template(text, ["album ratings", "music ratings"]);
  if (box) {
    const prm = params(box);
    const aggs = {};
    for (const [k, v] of Object.entries(prm)) aggs[k] = clean(v);
    for (let i = 1; i <= 5; i++) {
      const label = (aggs[`aggregate${i}`] || "").toLowerCase();
      if (label.includes("metacritic")) aggs.mc = aggs[`aggregate${i}score`] || "";
    }
    const mc = /^(\d{1,3})\s*\/\s*100/.exec(aggs.mc || "");
    if (mc) crit.push(`Metacritic ${mc[1]}`);
    const seen = new Set(), found = [];
    for (const k of Object.keys(prm).filter((x) => /^rev\d+$/.test(x)).sort((a, b) => a.slice(3) - b.slice(3))) {
      const name = outletName(prm[k]);
      const score = clean(prm[`${k}score`] || "");
      if (!name || !score || /needle drop|fantano/i.test(name) || seen.has(name)) continue;
      seen.add(name);
      if (PRIORITY.includes(name) && to10(score) != null) found.push({ name, score });
    }
    found.sort((a, b) => PRIORITY.indexOf(a.name) - PRIORITY.indexOf(b.name));
    crit.push(...found.slice(0, 5).map((c) => `${c.name} ${c.score}`));
  }
  const peaks = {};
  for (const t of text.matchAll(/\{\{\s*album ?chart\s*\|([^{}]*)\}\}/gi)) {
    const prm = params("{{x|" + t[1] + "}}");
    const key = CHARTS[(prm["1"] || "").trim().toLowerCase()];
    if (key && /^\d+$/.test((prm["2"] || "").trim())) peaks[key] = Math.min(Number(prm["2"]), peaks[key] || Infinity);
  }
  for (const k of ["US", "UK"]) if (peaks[k]) sales.push(`${k} #${peaks[k]}`);
  for (const t of text.matchAll(/\{\{\s*certification table entry/gi)) {
    if (sales.length >= 4) break;
    const whole = template(text.slice(t.index), ["certification table entry"]);
    if (!whole) continue;
    const prm = params(whole);
    const region = REGIONS[clean(prm.region).toLowerCase()];
    const award = clean(prm.award), mult = clean(prm.number);
    if (region && award) sales.push(`${region} ${/^\d+$/.test(mult) && mult !== "1" ? mult + "× " : ""}${award}`);
  }
  return { crit, sales };
}

// The article about this album, accepted only when its album infobox names the same album and artist; then its lines.
export async function wikiCritics(artist, album) {
  const na = norm(artist), nal = norm(album);
  if (!nal) return null;
  try {
    const q = new URLSearchParams({ action: "query", format: "json", formatversion: "2", generator: "search",
      gsrsearch: `${album} ${artist} album`, gsrlimit: "3", prop: "revisions", rvprop: "content", rvslots: "main" });
    const r = await fetch(`${WP_API}?${q}`, { headers: { "User-Agent": UA }, cf: { cacheTtl: 86400 } });
    if (!r.ok) return null;
    const pages = ((await r.json()).query || {}).pages || [];
    for (const p of pages.sort((a, b) => (a.index || 99) - (b.index || 99))) {
      const text = p.revisions && p.revisions[0] && p.revisions[0].slots && p.revisions[0].slots.main.content;
      const ib = text && template(text, ["infobox album", "infobox mixtape", "infobox ep"]);
      if (!ib) continue;
      const prm = params(ib);
      const names = [norm(clean(prm.name)), norm(p.title.replace(/\s*\(.*\)$/, ""))];
      const art = norm(clean(prm.artist));
      if (names.includes(nal) && art && na && (art.includes(na) || na.includes(art))) {
        const out = parse(text);
        return out.crit.length || out.sales.length ? { ...out, wp_url: "https://en.wikipedia.org/wiki/" + encodeURIComponent(p.title.replace(/ /g, "_")) } : null;
      }
    }
  } catch (e) {
    return null;
  }
  return null;
}
