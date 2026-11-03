// Reviews theneedledrop.com posted twice (lmn/rereviews.py gives the second post "dup_of": the first's id). The bot
// leaves the second post out, so anything people saved under its id is moved to the first one.

// {dup id: original id} from the raw archive
export function dupAliases(raw) {
  const out = {};
  for (const a of raw || []) if (a && a.dup_of) out[a.id] = a.dup_of;
  return out;
}

// the tables keyed by review_id whose rows belong to a person (or an anonymised vote)
export const DUP_TABLES = ["marks", "likes", "mood_votes", "follow_sent"];

// [sql, binds] pairs moving every row from a dup id to its original. Where the person has a row under both ids, the
// original's stays and the dup's is deleted (UPDATE OR IGNORE skips it, the DELETE removes it).
export function remapStatements(alias) {
  const out = [];
  for (const [dup, orig] of Object.entries(alias || {}).sort()) {
    for (const t of DUP_TABLES) {
      out.push([`UPDATE OR IGNORE ${t} SET review_id=? WHERE review_id=?`, [orig, dup]]);
      out.push([`DELETE FROM ${t} WHERE review_id=?`, [dup]]);
    }
  }
  return out;
}

// a short fingerprint of the alias list, so the move runs once per change of the list
export function aliasKey(alias) {
  return Object.entries(alias || {}).sort().map(([d, o]) => `${d}>${o}`).join(",");
}
