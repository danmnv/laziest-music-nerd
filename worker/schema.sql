-- Personal marks are visible only to their owner; the public sees only the average of visitor scores.
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,           -- Telegram ID; no name, username or photo is stored
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
CREATE TABLE IF NOT EXISTS likes (       -- «♡ Понравилось»: its own mark, which no status (heard, later, not mine) overwrites
  user_id INTEGER NOT NULL,
  review_id TEXT NOT NULL,              -- as in marks: a review, a MusicBrainz release group or "dz" + Deezer album ID
  liked_at TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS follows (      -- artists a person follows: a new review of theirs comes as a private message
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  name_key TEXT NOT NULL,                -- the artist's name, normalised (follow.mjs)
  mbid TEXT,                             -- MusicBrainz artist ID, when known; decides the match when both sides have one
  artist_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (user_id, name_key)
);
CREATE INDEX IF NOT EXISTS follows_name ON follows (name_key);
CREATE INDEX IF NOT EXISTS follows_mbid ON follows (mbid);
CREATE TABLE IF NOT EXISTS review_artists ( -- the artist of each card, sent by GitHub Actions before reviews.json catches up
  review_id TEXT PRIMARY KEY,
  artist_name TEXT NOT NULL,
  mbid TEXT
);
CREATE TABLE IF NOT EXISTS follow_sent (  -- who was already told about which review, so a retry never messages twice
  user_id INTEGER NOT NULL,
  review_id TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  PRIMARY KEY (user_id, review_id)
);
CREATE TABLE IF NOT EXISTS unreviewed (   -- albums without Fantano's review that someone opened: names for marks and reminders
  id TEXT PRIMARY KEY,                   -- MusicBrainz release group ID, or "dz" + Deezer album ID
  artist_name TEXT NOT NULL,
  album TEXT NOT NULL,
  year TEXT
);
CREATE TABLE IF NOT EXISTS watched_artists ( -- followed artists, checked on Deezer for new albums (releases.mjs)
  name_key TEXT PRIMARY KEY,             -- as in follows
  artist_name TEXT NOT NULL,
  dz_id INTEGER,                         -- Deezer artist ID, found through an album Fantano reviewed; NULL = not yet
  seen TEXT,                             -- JSON list of Deezer album IDs already known; NULL until the first check
  checked_at TEXT
);
CREATE TABLE IF NOT EXISTS new_releases (  -- albums found by that check; who was told is in follow_sent as "nr:<dz_id>"
  dz_id INTEGER PRIMARY KEY,
  name_key TEXT NOT NULL,
  artist_name TEXT NOT NULL,
  title TEXT NOT NULL,
  release_date TEXT,
  found_at TEXT NOT NULL
);
