import sqlite3
from datetime import datetime

DB_PATH = r"F:\spotify-ipod\synced_tracks.db"

def initialize_table():
    """Create SQLite table for track tracking"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(''
            CREATE TABLE IF NOT EXISTS synced_tracks (
                track_id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        '')
        conn.execute('PRAGMA synchronous = OFF')  # For faster writes

def check_existing(track_id=None, source_path=None):
    """Check if track_id or source_path already exists"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        if track_id:
            cursor.execute('SELECT 1 FROM synced_tracks WHERE track_id = ?', (track_id,))
        elif source_path:
            cursor.execute('SELECT 1 FROM synced_tracks WHERE source_path = ?', (source_path,))
        return cursor.fetchone() is not None

def insert_track(track_id, source_path):
    """Insert new synced track into database"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(''
            INSERT INTO synced_tracks (track_id, source_path)
            VALUES (?, ?)
        '', (track_id, source_path))
        conn.commit()