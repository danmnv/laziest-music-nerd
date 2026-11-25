// Share the discography request rate across Worker instances. The slot is taken
// atomically in D1, shortly before a request, rather than reserved far ahead.
const INTERVAL = 1100;
const DAY = 864e5;
const REFRESH_BACKOFF = 5 * 60e3;
export const DISCOGRAPHY_RETENTION = 14 * DAY;

export async function takeMusicBrainzSlot(db) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const now = Date.now();
    const slot = await db.prepare(
      "INSERT INTO settings (key,value) VALUES ('mb:discography-next',?) " +
      "ON CONFLICT(key) DO UPDATE SET value=excluded.value WHERE CAST(settings.value AS INTEGER)<=? RETURNING key",
    ).bind(String(now + INTERVAL), now).first();
    if (slot) return true;
    if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, INTERVAL));
  }
  return false;
}

// Cache the complete browse result, or an official-only indexed result when
// there is no complete browse result. Merge new reviews after reading the cache.
export async function musicBrainzCatalog(db, key, mbid, load) {
  const now = Date.now();
  let cached;
  if (key) {
    try {
      const row = await db.prepare("SELECT mbid, groups_json, fetched_at, complete FROM mb_discographies WHERE artist_key=? AND fetched_at>=?")
        .bind(key, now - DISCOGRAPHY_RETENTION).first();
      if (row && (!mbid || row.mbid === mbid)) {
        const groups = JSON.parse(row.groups_json);
        if (Array.isArray(groups) && groups.length) cached = { mbid: row.mbid, groups, fetched_at: row.fetched_at, complete: Boolean(row.complete) };
      }
    } catch (e) {
      console.warn("MusicBrainz discography cache read", e?.name);
    }
  }
  if (cached && now - cached.fetched_at < DAY) return cached;
  if (cached) {
    try {
      const refresh = await db.prepare(
        "UPDATE mb_discographies SET retry_after=? WHERE artist_key=? AND mbid=? AND fetched_at=? AND retry_after<=? RETURNING artist_key",
      ).bind(now + REFRESH_BACKOFF, key, cached.mbid, cached.fetched_at, now).first();
      if (!refresh) return { ...cached, stale: true };
    } catch {
      return { ...cached, stale: true };
    }
  }

  const fresh = await load(mbid || cached?.mbid, Boolean(cached?.complete));
  const save = fresh?.groups.length && (fresh.complete || (fresh.indexed && !cached?.complete));
  if (!save) return cached ? { ...cached, stale: true } : fresh;
  if (key) {
    try {
      await db.prepare(
        "INSERT INTO mb_discographies (artist_key,mbid,groups_json,fetched_at,complete) VALUES (?,?,?,?,?) " +
        "ON CONFLICT(artist_key) DO UPDATE SET mbid=excluded.mbid,groups_json=excluded.groups_json,fetched_at=excluded.fetched_at,complete=excluded.complete,retry_after=0 " +
        "WHERE excluded.fetched_at>=mb_discographies.fetched_at AND " +
        "(excluded.complete OR NOT mb_discographies.complete OR mb_discographies.fetched_at<?)",
      ).bind(key, fresh.mbid, JSON.stringify(fresh.groups), now, Number(fresh.complete), now - DISCOGRAPHY_RETENTION).run();
    } catch (e) {
      console.warn("MusicBrainz discography cache write", e?.name);
    }
  }
  return fresh;
}
