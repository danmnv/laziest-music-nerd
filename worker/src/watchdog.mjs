// The watchdog (2026-11-10): the owner hears about a silent stop. GitHub Actions run everything on a schedule, and when
// they stop altogether (the account was blocked on 2026-11-08; schedules didn't come back by themselves afterwards)
// there is no red run and no e-mail. So every check of new reviews tells the Worker "alive" (/api/heartbeat), and the
// Worker's hourly cron, which runs at Cloudflare and outlives GitHub, messages the owner when that goes quiet.
// Pure helpers; index.js does the requests.

export const SILENT_HOURS = 3; // checks come about once an hour (GitHub drops some scheduled runs); one may take 50 min
export const REPEAT_HOURS = 24; // still silent: once a day, not every hour

const hours = (from, to) => (to.getTime() - new Date(from).getTime()) / 36e5;

// seen: when the last check reported (ISO), alerted: when the owner was last told (ISO, or null/"" if not since the
// last check). -> hours of silence to tell the owner about, or 0 for "say nothing".
export function silentFor(seen, alerted, now) {
  if (!seen) return 0;
  const h = hours(seen, now);
  if (!(h >= SILENT_HOURS)) return 0;
  if (alerted && hours(alerted, now) < REPEAT_HOURS) return 0;
  return Math.floor(h);
}

// The data tokens (GitHub's fine-grained tokens that open the private data repo) end on a known day. The daily cron
// reminds the owner on these days before it, and on the day itself.
export const TOKEN_WARN_DAYS = [30, 14, 7, 3, 2, 1, 0];

// expires: "2027-10-31". -> whole days left (0 on the day, negative after), or null without a readable date.
export function daysLeft(expires, now) {
  const end = Date.parse(`${String(expires || "").trim()}T00:00:00Z`);
  if (Number.isNaN(end)) return null;
  return Math.floor((end - Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())) / 864e5);
}

// What GitHub Actions may ask the Worker to tell the owner (/api/alert): a fixed list, so the text is never theirs.
export const ALERTS = {
  llm: (code) => "⚠️ «Брифы для архива»: роутер Selectel не принял запрос" + (code ? ` (код ${code})` : "") +
    ". Обычно это значит, что на счёте кончились деньги (402) или ключ больше не подходит (401, 403). " +
    "Описания старых обзоров не пишутся, пока это не исправить. Остальное работает.",
};
