import sqlite3
from pathlib import Path

from ark_pi.workspace.catalog import utc_now_iso

_COMPLETION_SCHEMA = """
CREATE TABLE IF NOT EXISTS completed_documents (
    document_id TEXT PRIMARY KEY,
    content_digest TEXT NOT NULL,
    completed_at TEXT NOT NULL
);
"""


class CompletionLedger:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_COMPLETION_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "CompletionLedger":
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def is_completed(self, document_id: str) -> bool:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT 1 FROM completed_documents WHERE document_id = ? LIMIT 1",
            (document_id,),
        ).fetchone()
        return row is not None

    def get_digest(self, document_id: str) -> str | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT content_digest FROM completed_documents WHERE document_id = ? LIMIT 1",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def mark_completed(self, document_id: str, content_digest: str) -> None:
        assert self._conn is not None
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO completed_documents (document_id, content_digest, completed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                content_digest = excluded.content_digest,
                completed_at = excluded.completed_at
            """,
            (document_id, content_digest, now),
        )

    def commit(self) -> None:
        assert self._conn is not None
        self._conn.commit()

    def count(self) -> int:
        assert self._conn is not None
        row = self._conn.execute("SELECT COUNT(*) FROM completed_documents").fetchone()
        assert row is not None
        return int(row[0])
