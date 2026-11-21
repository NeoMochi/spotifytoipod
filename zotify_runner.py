import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Callable, Dict, Optional

from mutagen import File as MutagenFile
from mutagen import MutagenError
from mutagen.flac import Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TCON, USLT
from PIL import Image, ImageOps

import database
from spotify_fetcher import fetch_spotify_source

ROOT_DIR = Path(__file__).resolve().parent
RAW_DOWNLOADS = ROOT_DIR / "raw_downloads"
MUSIC_LIBRARY = ROOT_DIR / "music_library"
PLAYLISTS_DIR = MUSIC_LIBRARY / "Playlists"
AUDIO_EXTENSIONS = {".ogg", ".mp3", ".m4a", ".flac", ".wav"}
LOG_CALLBACK = Callable[[str], None]
LRC_TIMESTAMP = re.compile(r"\[\d{1,3}:\d{2}(?:\.\d{1,3})?\]")
LRC_METADATA = re.compile(r"^\[(?:ar|ti|al|by|re|ve|offset|length):.*\]$", re.I)
USER_AGENT = "SpotifyIpodNano7GPrep/1.0 (https://localhost)"


def validate_playlist_name(name: str) -> str:
    name = name.strip()
    if (
        not name
        or name in {".", ".."}
        or any(char in name for char in '\\/:*?"<>|')
        or name.endswith((".", " "))
        or name.split(".", 1)[0].upper()
        in {"CON", "PRN", "AUX", "NUL"}
        | {f"COM{i}" for i in range(1, 10)}
        | {f"LPT{i}" for i in range(1, 10)}
    ):
        raise ValueError("Use a valid Windows folder name for the playlist.")
    return name


class LocalMediaProcessor:
    def __init__(
        self,
        raw_downloads: Path = RAW_DOWNLOADS,
        music_library: Path = MUSIC_LIBRARY,
        log_callback: Optional[LOG_CALLBACK] = None,
        ffmpeg_path: Optional[str] = None,
    ):
        self.raw_downloads = Path(raw_downloads)
        self.music_library = Path(music_library)
        self.playlists_dir = self.music_library / "Playlists"
        self.log_callback = log_callback or print
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self._genre_cache: Dict[str, str] = {}

    def log(self, message: str) -> None:
        self.log_callback(str(message).rstrip())

    @staticmethod
    def _sidecar_art_candidates(source: Path):
        return [
            source.with_suffix(".jpg"),
            source.with_suffix(".jpeg"),
            source.with_suffix(".png"),
            source.with_suffix(".webp"),
            source.parent / "cover.jpg",
            source.parent / "cover.jpeg",
            source.parent / "cover.png",
            source.parent / "folder.jpg",
        ]

    def _track_id(self, playlist_name: str, playlist_root: Path, source: Path) -> str:
        relative_path = source.relative_to(playlist_root).as_posix().casefold()
        related_files = [source, source.with_suffix(".lrc")]
        related_files.extend(self._sidecar_art_candidates(source))
        signatures = []
        for related_file in dict.fromkeys(related_files):
            if not related_file.is_file():
                continue
            stat = related_file.stat()
            relative = related_file.relative_to(playlist_root).as_posix().casefold()
            signatures.append(f"{relative}\0{stat.st_size}\0{stat.st_mtime_ns}")
        fingerprint = f"{playlist_name.casefold()}\0{relative_path}\0" + "\0".join(
            signatures
        )
        return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()

    def _sidecar_artwork(self, source: Path) -> Optional[bytes]:
        for candidate in self._sidecar_art_candidates(source):
            if candidate.is_file():
                return candidate.read_bytes()
        return None

    @staticmethod
    def _as_values(value):
        return value if isinstance(value, (list, tuple)) else [value]

    def _embedded_artwork(self, source: Path) -> Optional[bytes]:
        try:
            audio = MutagenFile(str(source))
        except (MutagenError, OSError, ValueError) as exc:
            self.log(f"[Art Warning] Could not inspect {source.name}: {exc}")
            return None
        if audio is None:
            return None

        for picture in getattr(audio, "pictures", []):
            data = getattr(picture, "data", None)
            if data:
                return data

        tags = getattr(audio, "tags", None)
        if not tags:
            return None

        for key in tags.keys():
            value = tags[key]
            if str(key).startswith("APIC"):
                return value.data
            if key == "covr":
                for cover in self._as_values(value):
                    if cover:
                        return bytes(cover)
            if key == "coverart":
                for encoded in self._as_values(value):
                    try:
                        return base64.b64decode(encoded)
                    except (ValueError, TypeError):
                        continue
            if key == "metadata_block_picture":
                for encoded in self._as_values(value):
                    try:
                        raw_picture = base64.b64decode(encoded)
                        picture = Picture()
                        picture.load(BytesIO(raw_picture))
                        return picture.data
                    except (MutagenError, OSError, ValueError, TypeError):
                        continue
        return None

    def _find_artwork(self, source: Path) -> Optional[bytes]:
        return self._sidecar_artwork(source) or self._embedded_artwork(source)

    @staticmethod
    def _clean_lyrics(lrc_path: Path) -> Optional[str]:
        if not lrc_path.is_file():
            return None
        text = lrc_path.read_text(encoding="utf-8-sig", errors="replace")
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if not line or LRC_METADATA.match(line):
                continue
            cleaned = LRC_TIMESTAMP.sub("", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)

    @staticmethod
    def _resize_artwork(data: bytes) -> bytes:
        with Image.open(BytesIO(data)) as original:
            square = ImageOps.fit(
                original.convert("RGB"),
                (500, 500),
                method=Image.Resampling.LANCZOS,
            )
            buffer = BytesIO()
            square.save(
                buffer,
                format="JPEG",
                quality=90,
                progressive=False,
                optimize=False,
            )
        return buffer.getvalue()

    @staticmethod
    def _get_id3_text(tags: ID3, frame_id: str) -> str:
        frame = tags.get(frame_id)
        if frame is None:
            return ""
        texts = getattr(frame, "text", None)
        if not texts:
            return ""
        return str(texts[0]).strip()

    def _query_itunes_genre(self, artist: str, title: str) -> Optional[str]:
        search_term = f"{artist} {title}".strip()
        if not search_term:
            return None
        encoded_term = urllib.parse.quote_plus(search_term)
        url = f"https://itunes.apple.com/search?term={encoded_term}&entity=song&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except (OSError, ValueError, urllib.error.URLError):
            return None

        results = payload.get("results")
        if isinstance(results, list) and results:
            genre = str(results[0].get("primaryGenreName") or "").strip()
            if genre and genre.casefold() != "unknown":
                return genre
        return None

    def _query_musicbrainz_genre(self, artist: str) -> Optional[str]:
        cleaned_artist = artist.strip()
        if not cleaned_artist:
            return None
        encoded_artist = urllib.parse.quote(cleaned_artist)
        url = (
            f"https://musicbrainz.org/ws/2/artist/"
            f"?query=artist:{encoded_artist}&fmt=json&limit=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except (OSError, ValueError, urllib.error.URLError):
            return None

        artists = payload.get("artists")
        if not isinstance(artists, list) or not artists:
            return None

        tags = artists[0].get("tags")
        if not isinstance(tags, list) or not tags:
            return None

        best_name = None
        best_count = -1
        for tag_entry in tags:
            if not isinstance(tag_entry, dict):
                continue
            tag_name = str(tag_entry.get("name") or "").strip()
            if not tag_name or tag_name.casefold() == "unknown":
                continue
            try:
                count = int(tag_entry.get("count", 0))
            except (TypeError, ValueError):
                count = 0
            if count > best_count:
                best_count = count
                best_name = tag_name

        return best_name.title() if best_name else None

    def _resolve_genre(self, tags: ID3, mp3_path: Path) -> str:
        existing_genre = self._get_id3_text(tags, "TCON")
        if existing_genre and existing_genre.casefold() != "unknown":
            return existing_genre

        artist = self._get_id3_text(tags, "TPE1")
        title = self._get_id3_text(tags, "TIT2")

        if not artist and not title:
            stem = mp3_path.stem
            if stem.endswith(".partial"):
                stem = stem[: -len(".partial")]
            if " - " in stem:
                artist, title = [part.strip() for part in stem.split(" - ", 1)]
            else:
                title = stem.strip()

        cache_key = (
            artist.split(",")[0].split("/")[0].strip().casefold() if artist else ""
        )
        if cache_key and cache_key in self._genre_cache:
            return self._genre_cache[cache_key]

        genre = self._query_itunes_genre(artist, title)
        if not genre and artist:
            genre = self._query_musicbrainz_genre(artist)

        if genre:
            if cache_key:
                self._genre_cache[cache_key] = genre
            self.log(f"[Genre] Resolved '{genre}' for {artist or title}")
            return genre

        fallback = "Music"
        if cache_key:
            self._genre_cache[cache_key] = fallback
        self.log(f"[Genre] Defaulted to '{fallback}' for {artist or title}")
        return fallback

    def _write_ipod_tags(
        self,
        mp3_path: Path,
        artwork: Optional[bytes],
        lyrics: Optional[str],
    ) -> None:
        try:
            tags = ID3(str(mp3_path))
        except ID3NoHeaderError:
            tags = ID3()

        tags.delall("APIC")
        if artwork is not None:
            cover_bytes = self._resize_artwork(artwork)
            tags.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=cover_bytes,
                )
            )

        if lyrics is not None:
            tags.delall("USLT")
            if lyrics:
                tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))

        genre = self._resolve_genre(tags, mp3_path)
        tags.delall("TCON")
        tags.add(TCON(encoding=3, text=genre))

        tags.save(str(mp3_path), v2_version=3)

    def _run_ffmpeg(self, source: Path, temp_output: Path) -> None:
        if not self.ffmpeg_path:
            raise RuntimeError(
                "FFmpeg was not found. Install FFmpeg and add ffmpeg.exe to PATH."
            )

        command = [
            self.ffmpeg_path,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-map_metadata",
            "0",
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "320k",
            "-abr",
            "0",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-id3v2_version",
            "3",
            str(temp_output),
        ]
        self.log(f"[FFmpeg] Converting {source.name}")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if process.stdout is not None:
            for line in process.stdout:
                if line.strip():
                    self.log(line)
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"FFmpeg exited with code {return_code}.")
        if not temp_output.is_file() or temp_output.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not create an output MP3.")

    def _process_file(
        self,
        playlist_name: str,
        playlist_root: Path,
        source: Path,
        output: Path,
    ) -> bool:
        track_id = self._track_id(playlist_name, playlist_root, source)
        recorded_output = database.get_output_path(track_id)
        if (
            database.check_existing(track_id=track_id)
            and recorded_output
            and Path(recorded_output).is_file()
            and os.path.normcase(recorded_output) == os.path.normcase(str(output))
        ):
            self.log(f"[Skip] Already prepared: {source.name}")
            return False

        artwork = self._find_artwork(source)
        if artwork is None:
            self.log(
                f"[Art Warning] No embedded or matching sidecar cover image found for {source.name}."
            )

        lyrics = self._clean_lyrics(source.with_suffix(".lrc"))
        if lyrics is None:
            self.log(f"[Lyrics Warning] No matching LRC file for {source.name}.")

        output.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output.with_name(f"{output.stem}.partial.mp3")
        if temp_output.exists():
            temp_output.unlink()
        try:
            self._run_ffmpeg(source, temp_output)
            self._write_ipod_tags(temp_output, artwork, lyrics)
            temp_output.replace(output)
        finally:
            if temp_output.exists():
                temp_output.unlink()

        database.insert_track(track_id, str(source), str(output))
        self.log(f"[Ready] {output}")
        return True

    def _write_playlist(self, playlist_name: str, output_root: Path) -> Path:
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        playlist_file = self.playlists_dir / f"{playlist_name}.m3u"
        tracks = sorted(
            (
                path
                for path in output_root.rglob("*.mp3")
                if path.is_file() and ".partial." not in path.name
            ),
            key=lambda path: path.relative_to(output_root).as_posix().casefold(),
        )
        relative_paths = [
            Path(os.path.relpath(track, playlist_file.parent)).as_posix()
            for track in tracks
        ]
        temp_playlist = playlist_file.with_suffix(".m3u.tmp")
        with temp_playlist.open("w", encoding="utf-8", newline="\n") as file:
            file.write("#EXTM3U\n")
            for relative_path in relative_paths:
                file.write(relative_path + "\n")
        temp_playlist.replace(playlist_file)
        self.log(f"[Playlist] Updated {playlist_file} ({len(tracks)} tracks)")
        return playlist_file

    def process_playlist(
        self,
        playlist_name: str,
        source: str = "",
        build_playlist: bool = True,
    ) -> int:
        playlist_name = validate_playlist_name(playlist_name)
        playlist_root = self.raw_downloads / playlist_name
        output_root = self.music_library / playlist_name

        if source and source.strip():
            fetch_spotify_source(
                source=source,
                playlist_name=playlist_name,
                raw_downloads=self.raw_downloads,
                log_callback=self.log,
            )

        if not playlist_root.is_dir():
            self.log(f"[Error] Raw playlist folder does not exist: {playlist_root}")
            return 0

        database.initialize_table()
        sources = sorted(
            (
                path
                for path in playlist_root.rglob("*")
                if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
            ),
            key=lambda path: path.relative_to(playlist_root).as_posix().casefold(),
        )
        processed = 0
        used_outputs = set()
        for source_file in sources:
            relative = source_file.relative_to(playlist_root)
            relative_output = relative.with_suffix(".mp3")
            output_key = relative_output.as_posix().casefold()
            if output_key in used_outputs:
                relative_output = relative.with_name(
                    f"{relative.stem} [{relative.suffix.lstrip('.')}].mp3"
                )
                output_key = relative_output.as_posix().casefold()
            used_outputs.add(output_key)
            output = output_root / relative_output

            try:
                if self._process_file(
                    playlist_name, playlist_root, source_file, output
                ):
                    processed += 1
            except (MutagenError, OSError, RuntimeError, ValueError) as exc:
                self.log(f"[Error] {source_file}: {exc}")

        if build_playlist:
            self._write_playlist(playlist_name, output_root)
        else:
            self.log(
                f"[Playlist] Skipped .m3u generation for '{playlist_name}' (playlist building off)."
            )

        if not sources:
            self.log(f"[Info] No supported audio files found in {playlist_root}.")
        return processed

    def process_playlists(self, playlists) -> int:
        total = 0
        for item in playlists:
            if isinstance(item, dict):
                name = item.get("name", "")
                source = item.get("source", "") or ""
                build_playlist = bool(item.get("build_playlist", True))
            else:
                name = str(item)
                source = ""
                build_playlist = True
            total += self.process_playlist(name, source, build_playlist=build_playlist)
        return total