from contextlib import closing
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "synced_tracks.db"


def initialize_table():
    """Create or upgrade the local track-processing table."""
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(db_path))) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS synced_tracks (
                    track_id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(synced_tracks)")
            }
            if "output_path" not in columns:
                conn.execute("ALTER TABLE synced_tracks ADD COLUMN output_path TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_synced_tracks_source_path "
                "ON synced_tracks(source_path)"
            )


def check_existing(
    track_id: Optional[str] = None, source_path: Optional[str] = None
) -> bool:
    """Return whether a matching track ID or source path was processed."""
    conditions = []
    values = []
    if track_id is not None:
        conditions.append("track_id = ?")
        values.append(track_id)
    if source_path is not None:
        conditions.append("source_path = ?")
        values.append(source_path)
    if not conditions:
        raise ValueError("Provide a track_id or source_path to check.")

    query = "SELECT 1 FROM synced_tracks WHERE " + " OR ".join(conditions) + " LIMIT 1"
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        return conn.execute(query, values).fetchone() is not None


def get_output_path(track_id: str) -> Optional[str]:
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        row = conn.execute(
            "SELECT output_path FROM synced_tracks WHERE track_id = ?",
            (track_id,),
        ).fetchone()
    return row[0] if row else None


def insert_track(
    track_id: str, source_path: str, output_path: Optional[str] = None
) -> None:
    """Record a successfully processed source and its output file."""
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO synced_tracks (track_id, source_path, output_path)
                VALUES (?, ?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    source_path = excluded.source_path,
                    output_path = excluded.output_path,
                    timestamp = CURRENT_TIMESTAMP
                """,
                (track_id, source_path, output_path),
            )
