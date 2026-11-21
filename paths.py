"""Locations of the app's data and bundled tools.

Everything the app creates lives next to the program: next to the .exe when
packaged, or next to the source files when run with Python. Helper programs
(ffmpeg, spotdl) are looked for in a ``tools`` folder there first, then PATH.
"""

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_tool(name: str) -> Optional[str]:
    exe_name = f"{name}.exe" if os.name == "nt" else name
    base = app_dir()
    for candidate in (base / "tools" / exe_name, base / exe_name):
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def spotdl_command() -> Optional[List[str]]:
    """Command that starts spotDL, or None when it cannot be found."""
    if is_frozen():
        tool = find_tool("spotdl")
        return [tool] if tool else None
    return [sys.executable, "-m", "spotdl"]
