import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

LOG_CALLBACK = Callable[[str], None]


def _stream_process(
    command: List[str],
    env: Dict[str, str],
    log_callback: LOG_CALLBACK,
) -> Tuple[int, List[str]]:
    output_lines: List[str] = []
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            if line.strip():
                log_callback(line)
            output_lines.append(line)
    return_code = process.wait()
    return return_code, output_lines


def fetch_spotify_source(
    source: str,
    playlist_name: str,
    raw_downloads: Path,
    log_callback: LOG_CALLBACK = print,
) -> bool:
    cleaned_source = (source or "").strip()
    if not cleaned_source:
        return True

    raw_downloads = Path(raw_downloads)
    target_dir = raw_downloads / playlist_name
    target_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    is_liked = cleaned_source.lower() in {"liked", "saved"}
    spotdl_query = "saved" if is_liked else cleaned_source

    spotdl_cmd = [
        sys.executable,
        "-m",
        "spotdl",
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
    ]
    if is_liked:
        spotdl_cmd.append("--user-auth")

    log_callback(f"[spotDL] Downloading '{playlist_name}' ({cleaned_source})...")
    try:
        spotdl_code, _ = _stream_process(spotdl_cmd, env, log_callback)
        return spotdl_code == 0
    except OSError as exc:
        log_callback(f"[spotDL Error] Could not run spotDL: {exc}")
        return False