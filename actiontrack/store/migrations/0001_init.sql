-- Schema v1 (M6 spec §3). Root spec §8 plus gaps G1 (nullable people.email) and G2 (parsed fields
-- in item_sources). The migration runner sets PRAGMA user_version.

CREATE TABLE notes (
  path         TEXT PRIMARY KEY,
  sha256       TEXT,                 -- NULL for a skipped note that could not be read
  meeting_date DATE,
  title        TEXT,
  ingested_at  TIMESTAMP NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('ok','skipped')),
  skip_reason  TEXT,
  skip_detail  TEXT
);

CREATE TABLE people (
  key        TEXT PRIMARY KEY,
  full_name  TEXT NOT NULL,
  first_name TEXT NOT NULL,
  email      TEXT                    -- G1: NULL for a first-name-only attendee
);

CREATE TABLE items (
  id            TEXT PRIMARY KEY,
  owner_key     TEXT,
  owner_display TEXT,
  owner_raw     TEXT,
  task          TEXT NOT NULL,
  task_norm     TEXT NOT NULL,
  due_date      DATE,
  due_raw       TEXT,
  status        TEXT NOT NULL CHECK (status IN ('open','done')),
  done_source   TEXT CHECK (done_source IN ('note','cli')),
  done_at       TIMESTAMP,
  flags         TEXT NOT NULL DEFAULT '[]',
  first_seen    DATE NOT NULL,
  last_seen     DATE NOT NULL
);

CREATE TABLE item_sources (
  note_path        TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
  line_no          INTEGER NOT NULL,
  item_id          TEXT REFERENCES items(id) ON DELETE SET NULL,
  raw_text         TEXT NOT NULL,
  meeting_date     DATE NOT NULL,
  note_title       TEXT,
  owner_key        TEXT,
  owner_display    TEXT,
  owner_raw        TEXT,
  owner_flags      TEXT NOT NULL DEFAULT '[]',
  owner_candidates TEXT NOT NULL DEFAULT '[]',
  task             TEXT NOT NULL,
  due_date         DATE,
  due_raw          TEXT,
  checked          INTEGER NOT NULL,
  flags            TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (note_path, line_no)
);

CREATE TABLE drafts (
  id             INTEGER PRIMARY KEY,
  owner_key      TEXT NOT NULL,
  recipient      TEXT NOT NULL,
  gmail_draft_id TEXT,
  created_at     TIMESTAMP NOT NULL,
  item_ids       TEXT NOT NULL
);

CREATE INDEX ix_items_owner ON items(owner_key);
CREATE INDEX ix_items_status_due ON items(status, due_date);
CREATE INDEX ix_sources_item ON item_sources(item_id);
CREATE INDEX ix_sources_note ON item_sources(note_path);
