import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from mutagen.id3 import ID3, APIC, USLT
from PIL import Image

import database
from zotify_runner import LocalMediaProcessor


class FakeFFmpegProcess:
    def __init__(self, command):
        self.command = command
        self.stdout = io.StringIO("fake ffmpeg completed\n")
        self.returncode = 0
        Path(command[-1]).write_bytes(b"fake mp3 data")

    def wait(self):
        return self.returncode


class LocalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.raw_root = self.root / "raw_downloads"
        self.music_root = self.root / "music_library"
        self.playlist_root = self.raw_root / "Flying Mix"
        self.playlist_root.mkdir(parents=True)
        self.database_path = self.root / "synced_tracks.db"
        self.original_db_path = database.DB_PATH
        database.DB_PATH = self.database_path
        database.initialize_table()

        self.source = self.playlist_root / "Artist - Song.ogg"
        self.source.write_bytes(b"local audio placeholder")
        Image.new("RGB", (120, 80), "red").save(
            self.playlist_root / "Artist - Song.jpg"
        )
        (self.playlist_root / "Artist - Song.lrc").write_text(
            "[ar:Example Artist]\n"
            "[00:01.00]First line\n"
            "[00:02.30]Second line\n",
            encoding="utf-8",
        )
        self.processor = LocalMediaProcessor(
            self.raw_root,
            self.music_root,
            log_callback=lambda _message: None,
            ffmpeg_path="ffmpeg",
        )

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_converts_tags_exports_playlist_and_skips_repeat(self):
        processes = []

        def fake_popen(command, **_kwargs):
            process = FakeFFmpegProcess(command)
            processes.append(process)
            return process

        with patch("zotify_runner.subprocess.Popen", side_effect=fake_popen):
            self.assertEqual(self.processor.process_playlist("Flying Mix"), 1)
            self.assertEqual(self.processor.process_playlist("Flying Mix"), 0)

        self.assertEqual(len(processes), 1)
        command = processes[0].command
        self.assertEqual(command[command.index("-b:a") + 1], "320k")
        self.assertEqual(command[command.index("-ar") + 1], "44100")
        self.assertEqual(
            command[command.index("-af") + 1],
            "loudnorm=I=-14:TP=-1.5:LRA=11",
        )

        output = self.music_root / "Flying Mix" / "Artist - Song.mp3"
        tags = ID3(str(output))
        self.assertEqual(tags.version, (2, 3, 0))
        self.assertEqual(len(tags.getall("APIC")), 1)
        self.assertEqual(len(tags.getall("USLT")), 1)
        self.assertEqual(
            tags.getall("USLT")[0].text,
            "First line\nSecond line",
        )
        with Image.open(io.BytesIO(tags.getall("APIC")[0].data)) as artwork:
            self.assertEqual(artwork.format, "JPEG")
            self.assertEqual(artwork.size, (500, 500))

        playlist = self.music_root / "Playlists" / "Flying Mix.m3u"
        self.assertEqual(
            playlist.read_text(encoding="utf-8").splitlines(),
            ["#EXTM3U", "../Flying Mix/Artist - Song.mp3"],
        )

    def test_missing_artwork_is_not_recorded(self):
        no_art_playlist = self.raw_root / "No Art"
        no_art_playlist.mkdir()
        source = no_art_playlist / "No Art.flac"
        source.write_bytes(b"local audio placeholder")

        with patch("zotify_runner.subprocess.Popen") as popen:
            self.processor.process_playlist("No Art")

        self.assertFalse(popen.called)
        self.assertFalse(
            database.check_existing(source_path=str(source))
        )

    def test_sidecar_changes_trigger_reprocessing(self):
        processes = []

        def fake_popen(command, **_kwargs):
            process = FakeFFmpegProcess(command)
            processes.append(process)
            return process

        with patch("zotify_runner.subprocess.Popen", side_effect=fake_popen):
            self.assertEqual(self.processor.process_playlist("Flying Mix"), 1)
            (self.playlist_root / "Artist - Song.lrc").write_text(
                "[00:01.00]Updated lyric\n",
                encoding="utf-8",
            )
            self.assertEqual(self.processor.process_playlist("Flying Mix"), 1)

        self.assertEqual(len(processes), 2)

    def test_migrates_existing_database_with_output_path(self):
        legacy_path = self.root / "legacy.db"
        with closing(sqlite3.connect(str(legacy_path))) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE synced_tracks (
                        track_id TEXT PRIMARY KEY,
                        source_path TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
        database.DB_PATH = legacy_path

        database.initialize_table()

        with closing(sqlite3.connect(str(legacy_path))) as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(synced_tracks)")
            }
        self.assertIn("output_path", columns)


if __name__ == "__main__":
    unittest.main()
