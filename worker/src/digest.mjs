// Which Sundays get the biweekly digest. GitHub/Cloudflare cron can't say "every other week",
// so the Worker runs every Sunday and sends only on every second one.
//
// Counted in whole weeks from a fixed digest Sunday rather than by ISO week parity: ISO years with
// 53 weeks (2026 is one) put two odd weeks in a row (53, then 1), which would skip a digest and leave
// reviews from one week out of every digest.
const WEEK_MS = 7 * 864e5;
const ANCHOR = Date.UTC(2026, 10, 1); // Sunday 1 Nov 2026, a digest day

export function isDigestSunday(date) {
  const weeks = Math.floor((date.getTime() - ANCHOR) / WEEK_MS);
  return ((weeks % 2) + 2) % 2 === 0;
}
