# M6 — SQLite Store

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M0 |
| **Files** | `actiontrack/store/db.py`, `actiontrack/store/repo.py`, `actiontrack/store/migrations/0001_init.sql` |
| **REQ IDs** | REQ-STORE-01 … 06 |

## 1. Purpose
Persist notes, parsed sources, people, merged items and draft records. Expose small repositories so that services never write SQL.
Overdue is computed at query time.

## 2. Connection (REQ-STORE-04, REQ-STORE-05)

```python
def connect(path: Path) -> sqlite3.Connection
    # mkdir -p parent; sqlite3.connect(path, detect_types=PARSE_DECLTYPES, isolation_level=None)
    # PRAGMA journal_mode=WAL; busy_timeout=5000; foreign_keys=ON; row_factory=sqlite3.Row; migrate(conn)
@contextmanager
def transaction(conn) -> Iterator[None]
    # BEGIN IMMEDIATE … COMMIT; ROLLBACK on any BaseException (incl. KeyboardInterrupt), then re-raise
def migrate(conn) -> None
    # applies migrations/NNNN_*.sql in order where NNNN > PRAGMA user_version; each in its own transaction
```
- `path == Path(":memory:")` is supported for tests.
- A DB with `user_version` greater than the latest known migration → `FatalError("database was created by a newer actiontrack")`.
- `sqlite3.OperationalError` "unable to open" / read-only → `FatalError` with the path.

## 3. Schema v1 (REQ-STORE-01, REQ-STORE-06)

Extends root spec §8 with gaps G1 and G2 (nullable `people.email`, parsed fields in `item_sources`).

```sql
CREATE TABLE notes (
  path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, meeting_date DATE, title TEXT,
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
PRAGMA user_version = 1;
```
JSON columns (`flags`, `owner_flags`, `owner_candidates`, `item_ids`) hold sorted JSON arrays of strings.

## 4. Repositories — `repo.py`

```python
class NoteRepo:
    def get(self, path: Path) -> NoteRow | None             # sha256, status
    def upsert_ok(self, meta: NoteMeta, *, now: datetime) -> None
    def upsert_skipped(self, rec: SkipRecord, *, sha256: str | None, now: datetime) -> None   # also deletes its sources
    def paths_under(self, root: Path) -> list[Path]
    def delete(self, path: Path) -> None                     # cascades sources

class SourceRepo:
    def replace_for_note(self, path: Path, items: Sequence[ParsedItem]) -> None
    def all(self) -> list[ParsedItem]                        # rebuilt ParsedItems, deterministic order
    def count(self) -> int

class PeopleRepo:
    def upsert_many(self, attendees: Iterable[Attendee]) -> None   # an explicit email never overwritten by None
    def find(self, query: str) -> list[Person]               # key, email, full name, or first name (normalized)
    def get(self, key: str) -> Person | None

class ItemRepo:
    def existing(self) -> list[ExistingItem]
    def apply_groups(self, result: DedupResult) -> None
        # upsert every group; reassign item_sources.item_id; add ORPHANED flag to orphaned_ids (status untouched);
        # remove ORPHANED from groups that have sources again
    def query(self, f: ItemFilter, *, today: date) -> list[ItemRow]
    def ids(self) -> list[str]
    def get(self, item_id: str) -> ItemRow | None
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
    source_count: int; is_overdue: bool; sources: tuple[SourceRef, ...]   # (path, line_no, meeting_date, note_title)
```

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
G1 and G2 need confirming in the root spec §8.
