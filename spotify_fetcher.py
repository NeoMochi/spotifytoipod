import os
from pathlib import Path
from typing import Callable

import paths
from procutil import stream_process

LOG_CALLBACK = Callable[[str], None]
ORDER_FILE_NAME = ".spotify_order.m3u8"


def order_file_for(target_dir: Path) -> Path:
    """Where spotDL records the playlist's tracks in Spotify order."""
    return Path(target_dir) / ORDER_FILE_NAME


def fetch_spotify_source(
    source: str,
    playlist_name: str,
    raw_downloads: Path,
    log_callback: LOG_CALLBACK = print,
) -> bool:
    """Download a Spotify URL (or 'liked') with spotDL. True on success."""
    cleaned_source = (source or "").strip()
    if not cleaned_source:
        return True

    raw_downloads = Path(raw_downloads)
    target_dir = raw_downloads / playlist_name
    target_dir.mkdir(parents=True, exist_ok=True)

    base_command = paths.spotdl_command()
    if base_command is None:
        log_callback(
            "[spotDL Error] spotdl was not found. Put spotdl.exe in the 'tools' "
            "folder next to the app."
        )
        return False

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    is_liked = cleaned_source.lower() in {"liked", "saved"}
    spotdl_query = "saved" if is_liked else cleaned_source

    order_file = order_file_for(target_dir)
    try:
        order_file.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        log_callback(f"[spotDL Warning] Could not clear old track order: {exc}")

    spotdl_cmd = base_command + [
        "download",
        spotdl_query,
        "--output",
        str(target_dir / "{artists} - {title}.{output-ext}"),
        "--format",
        "mp3",
        "--bitrate",
        "320k",
        "--fetch-albums",
        "--generate-lrc",
        "--m3u",
        str(order_file),
    ]
    if is_liked:
        spotdl_cmd.append("--user-auth")

    log_callback(f"[spotDL] Downloading '{playlist_name}' ({cleaned_source})...")
    try:
        spotdl_code, _ = stream_process(spotdl_cmd, log_callback, env)
    except OSError as exc:
        log_callback(f"[spotDL Error] Could not run spotDL: {exc}")
        return False
    if spotdl_code != 0:
        log_callback(f"[spotDL Error] spotDL exited with code {spotdl_code}.")
        return False
    return True
