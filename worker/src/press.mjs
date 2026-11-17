// A Telegram button can toggle a value. Commit the receipt and the toggle in the same D1 transaction.
const PRESS = "SELECT value FROM telegram_presses WHERE update_id=? AND attempt=?";
const CLEARS_MARK = "EXISTS (" + PRESS + " AND value IS NULL)";

export async function applyPress(db, updateId, uid, rid, action, status, at) {
  // Real webhook updates always have an integer update_id.
  const attempt = crypto.randomUUID();
  const key = [String(updateId ?? attempt), attempt];
  const put = (sql, ...params) => db.prepare(sql).bind(...params);
  const snapshot = action === "lk"
    ? "SELECT CASE WHEN EXISTS (SELECT 1 FROM likes WHERE user_id=? AND review_id=?) THEN 'off' ELSE 'on' END, 0"
    : "SELECT CASE WHEN m.status=? THEN NULL ELSE ? END, " +
      "CASE WHEN ?='nope' AND m.status IS NOT 'nope' THEN EXISTS (SELECT 1 FROM likes WHERE user_id=? AND review_id=?) ELSE 0 END " +
      "FROM (SELECT 1) LEFT JOIN marks m ON m.user_id=? AND m.review_id=?";
  const values = action === "lk" ? [uid, rid] : [status, status, status, uid, rid, uid, rid];
  const claim = put(
    "INSERT OR IGNORE INTO telegram_presses (update_id, attempt, user_id, received_at, value, cleared_like) " +
    "SELECT ?,?,?,?,s.* FROM (" + snapshot + ") s", ...key, uid, at, ...values
  );

  let writes;
  if (action === "lk") {
    writes = [
      put("INSERT OR IGNORE INTO likes (user_id, review_id, liked_at) SELECT ?,?,? WHERE (" + PRESS + ")='on'", uid, rid, at, ...key),
      put("DELETE FROM likes WHERE user_id=? AND review_id=? AND (" + PRESS + ")='off'", uid, rid, ...key),
      // As before, liking an album marked «Не моё» switches it to «Слушал».
      put("UPDATE marks SET status='done', updated_at=?, later_at=NULL WHERE user_id=? AND review_id=? AND status='nope' " +
        "AND (" + PRESS + ")='on'", at, uid, rid, ...key),
    ];
  } else {
    writes = [
      put("INSERT INTO marks (user_id, review_id, status, score, updated_at, later_at) " +
        "SELECT ?,?, p.value, m.score, ?, CASE WHEN p.value='later' THEN ? END " +
        "FROM telegram_presses p LEFT JOIN marks m ON m.user_id=? AND m.review_id=? " +
        "WHERE p.update_id=? AND p.attempt=? AND (p.value IS NOT NULL OR m.score IS NOT NULL) " +
        "ON CONFLICT(user_id, review_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, later_at=excluded.later_at",
        uid, rid, at, at, uid, rid, ...key),
      put("DELETE FROM marks WHERE user_id=? AND review_id=? AND score IS NULL AND " + CLEARS_MARK, uid, rid, ...key),
      put("DELETE FROM likes WHERE user_id=? AND review_id=? AND (" + PRESS + ")='nope'", uid, rid, ...key),
    ];
  }
  const [result] = await db.batch([claim, ...writes]);
  if (!result.meta.changes) return null;
  return put("SELECT value, cleared_like FROM telegram_presses WHERE update_id=? AND attempt=?", ...key).first();
}
