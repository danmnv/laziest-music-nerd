// The critics/charts lines of a bot card, from the site's rt/<id>.json (built from data/ratings.json; source:
// the album's Wikipedia article). Kept out of index.js: named exports of the Worker's entry module count as entrypoints.

function esc(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function criticsText(rt) {
  if (!rt) return "";
  const src = rt.wp_url ? ` (<a href="${esc(rt.wp_url)}">Википедия</a>)` : "";
  const lines = [];
  if (rt.contested) lines.push(`⚡ Спорно: ${esc(rt.contested)}`); // Fantano vs the critics' average, 4+ points apart
  if (rt.crit && rt.crit.length) lines.push(`Критики: ${esc(rt.crit.join(" · "))}${src}`);
  if (rt.sales && rt.sales.length) lines.push(`Чарты и продажи: ${esc(rt.sales.join(" · "))}${lines.length ? "" : src}`);
  return lines.length ? "\n" + lines.join("\n") : "";
}
