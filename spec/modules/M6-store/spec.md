# M6 — SQLite Store

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M0. Uses `normalize_task` and `DedupResult` (M5) and `normalize_name` (M2) |
| **Files** | `actiontrack/store/db.py`, `actiontrack/store/repo.py`, `actiontrack/store/migrations/0001_init.sql` |
| **REQ IDs** | REQ-STORE-01 … 06 |

## 1. Purpose
Persist notes, parsed sources, people, merged items and draft records. Expose small repositories so that services never write SQL.
Overdue is computed at query time.

## 2. Connection (REQ-STORE-04, REQ-STORE-05)

```python
def connect(path: Path) -> sqlite3.Connection
    # mkdir -p parent; sqlite3.connect(path, isolation_level=None)
    # PRAGMA journal_mode=WAL; busy_timeout=5000; foreign_keys=ON; row_factory=sqlite3.Row; migrate(conn)
@contextmanager
def transaction(conn) -> Iterator[None]
    # BEGIN IMMEDIATE … COMMIT; ROLLBACK on any BaseException (incl. KeyboardInterrupt), then re-raise.
    # Re-entrant: inside an open transaction it does nothing and the outer block owns the commit.
def migrate(conn) -> None
    # applies migrations/NNNN_*.sql in order where NNNN > PRAGMA user_version; each in its own transaction
```
- `path == Path(":memory:")` (`db.MEMORY`) is supported for tests.
- A DB with `user_version` greater than the latest known migration → `FatalError("database was created by a newer actiontrack")`.
- Any `sqlite3.DatabaseError` while opening (unable to open, read-only, not a database) or an `OSError` creating the parent
  directory → `FatalError` naming the path.
- **No `detect_types`.** Python 3.12 deprecates the default date/datetime adapters, so dates and timestamps are stored as ISO-8601
  text and converted in `repo.py`. ISO dates compare correctly as text.
- The runner, not the SQL file, sets `PRAGMA user_version = NNNN` (inside the migration's transaction). If a migration fails but
  `user_version` has meanwhile reached its number (another process applied it), the failure is ignored.
- Repository methods that run several statements (`upsert_skipped`, `replace_for_note`, `apply_groups`) wrap themselves in
  `transaction`, so they are atomic on their own and join a caller's transaction (M7) when there is one.

## 3. Schema v1 (REQ-STORE-01, REQ-STORE-06)

Extends root spec §8 with gaps G1 and G2 (nullable `people.email`, parsed fields in `item_sources`).

```sql
CREATE TABLE notes (
  path TEXT PRIMARY KEY, sha256 TEXT, meeting_date DATE,          -- sha256 NULL: skipped, unreadable title TEXT,
  ingested_at TIMESTAMP NOT NULL, status TEXT NOT NULL CHECK (status IN ('ok','skipped')),
  skip_reason TEXT, skip_detail TEXT
);
CREATE TABLE people (
  key TEXT PRIMARY KEY, full_name TEXT NOT NULL, first_name TEXT NOT NULL, email TEXT   -- G1: nullable
);
CREATE TABLE items (
  id TEXT PRIMARY KEY, owner_key TEXT, owner_display TEXT, owner_raw TEXT,
  task TEXT NOT NULL, task_norm TEXT NOT NULL, due_date DATE, due_raw TEXT,
  status TEXT NOT NULL CHECK (status IN ('open','done')),
  done_source TEXT CHECK (done_source IN ('note','cli')), done_at TIMESTAMP,
  flags TEXT NOT NULL DEFAULT '[]', first_seen DATE NOT NULL, last_seen DATE NOT NULL
);
CREATE TABLE item_sources (                                   -- G2
  note_path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
  line_no INTEGER NOT NULL,
  item_id TEXT REFERENCES items(id) ON DELETE SET NULL,
  raw_text TEXT NOT NULL, meeting_date DATE NOT NULL, note_title TEXT,
  owner_key TEXT, owner_display TEXT, owner_raw TEXT, owner_flags TEXT NOT NULL DEFAULT '[]',
  owner_candidates TEXT NOT NULL DEFAULT '[]',
  task TEXT NOT NULL, due_date DATE, due_raw TEXT, checked INTEGER NOT NULL,
  flags TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (note_path, line_no)
);
CREATE TABLE drafts (
  id INTEGER PRIMARY KEY, owner_key TEXT NOT NULL, recipient TEXT NOT NULL,
  gmail_draft_id TEXT, created_at TIMESTAMP NOT NULL, item_ids TEXT NOT NULL
);
CREATE INDEX ix_items_owner ON items(owner_key);
CREATE INDEX ix_items_status_due ON items(status, due_date);
CREATE INDEX ix_sources_item ON item_sources(item_id);
CREATE INDEX ix_sources_note ON item_sources(note_path);
```
JSON columns hold JSON arrays of strings: flag sets (`flags`, `owner_flags`) sorted; sequences (`owner_candidates`, `item_ids`)
in their given order. Paths are stored as POSIX strings.

## 4. Repositories — `repo.py`

```python
class NoteRepo:
    def get(self, path: Path) -> NoteRow | None
    def upsert_ok(self, meta: NoteMeta, *, now: datetime) -> None
    def upsert_skipped(self, rec: SkipRecord, *, sha256: str | None, now: datetime) -> None   # also deletes its sources
    def paths_under(self, root: Path) -> list[Path]          # by path parts: notes2/ is not under notes/
    def delete(self, path: Path) -> None                     # cascades sources

class SourceRepo:
    def replace_for_note(self, path: Path, items: Sequence[ParsedItem]) -> None   # ValueError if an item is from another note
    def all(self) -> list[ParsedItem]                        # rebuilt, ordered by (meeting_date, path, line_no)
    def count(self) -> int

class PeopleRepo:
    def upsert_many(self, attendees: Iterable[Attendee]) -> None   # email = explicit or derived; never overwritten by None
    def find(self, query: str) -> list[Person]               # key, email, full name, or first name (normalize_name), by key
    def get(self, key: str) -> Person | None

class ItemRepo:
    def existing(self) -> list[ExistingItem]
        # task_norms = the item's task_norm ∪ normalize_task(task) of every source linked to it
    def apply_groups(self, result: DedupResult) -> None
        # upsert every group; unlink all sources, then link each group's sources; add ORPHANED flag to orphaned_ids
        # (status untouched, unknown ids ignored); group flags replace the stored ones, so ORPHANED goes when sources return
    def query(self, f: ItemFilter, *, today: date) -> list[ItemRow]
    def ids(self) -> list[str]                               # sorted, orphaned included
    def get(self, item_id: str, *, today: date) -> ItemRow | None   # orphaned included; `today` for is_overdue
    def mark_done(self, item_id: str, *, now: datetime) -> bool   # False if already done

class DraftRepo:
    def record(self, *, owner_key: str, recipient: str, gmail_draft_id: str | None, item_ids: Sequence[str], now: datetime) -> int

@dataclass(frozen=True)
class ItemFilter:
    owner_keys: tuple[str, ...] | None = None
    status: Literal["open", "done", "overdue"] | None = None
    due_before: date | None = None
    unassigned: bool = False
    flag: Flag | None = None
    include_orphaned: bool = False

@dataclass(frozen=True)
class ItemRow:   # ItemGroup fields minus sources, plus:
    source_count: int; is_overdue: bool; sources: tuple[SourceRef, ...]   # ordered by (meeting_date, path, line_no)

@dataclass(frozen=True)
class SourceRef:  path: Path; line_no: int; meeting_date: date; note_title: str | None

@dataclass(frozen=True)
class NoteRow:
    path: Path; sha256: str | None; status: Literal["ok", "skipped"]; meeting_date: date | None; title: str | None
    ingested_at: datetime; skip_reason: str | None; skip_detail: str | None
```

**Rebuilt sources.** `SourceRepo.all()` cannot restore what is not stored: `due.span` is `None`, and `due.flags` is
`flags ∩ {NO_DUE, UNPARSED_DUE}` (M4 builds `flags = owner.flags | due.flags | MULTI_OWNER`, and M3 only emits those two).

## 5. Query semantics (REQ-STORE-02)
- `is_overdue = status='open' AND due_date IS NOT NULL AND due_date < :today`, computed in SQL. It is never stored.
- `status="open"` includes overdue items. `status="overdue"` gives only the overdue ones. `status=None` gives everything.
- `due_before` → `due_date IS NOT NULL AND due_date < :d`.
- `unassigned` → `owner_key IS NULL`.
- `flag` → `EXISTS (SELECT 1 FROM json_each(items.flags) WHERE value = :flag)`.
- Orphaned items are excluded unless `include_orphaned` is set or `flag == ORPHANED` (gap G3).
- Order: `due_date IS NULL, due_date, owner_display, id`.

## 6. Out of scope
Deciding groups (M5). Deciding when to ingest (M7). Output formatting.

## 7. Open questions
None. G1 and G2 are confirmed in the root spec §8, together with the other schema changes this module makes: nullable
`notes.sha256` (a note skipped with `READ_ERROR` has no hash, so it is retried on every ingest), `notes.skip_detail`,
`items.owner_display` and `drafts.recipient`.
