-- Personal marks are visible only to their owner; the public sees only the average of visitor scores.
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,           -- Telegram ID, the only thing we store about a person
  dm_pinned_id INTEGER,                  -- pinned list message in the private chat with the bot
  started_at TEXT
);
CREATE TABLE IF NOT EXISTS marks (
  user_id INTEGER NOT NULL,
  review_id TEXT NOT NULL,
  status TEXT CHECK (status IN ('later','done','nope')),
  score INTEGER CHECK (score BETWEEN 0 AND 10),
  updated_at TEXT NOT NULL,
  later_at TEXT,                         -- when it was put on 'later', for the 21-day reminder
  reminded_at TEXT,
  PRIMARY KEY (user_id, review_id)
);
CREATE TABLE IF NOT EXISTS mood_votes (
  user_id INTEGER NOT NULL,
  review_id TEXT NOT NULL,
  mood TEXT NOT NULL,
  vote TEXT CHECK (vote IN ('y','n')),
  PRIMARY KEY (user_id, review_id, mood)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
