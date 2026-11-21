"""Run helper programs with live log output and a shared cancel switch."""

import subprocess
import threading
from typing import Callable, Dict, List, Optional, Tuple

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_lock = threading.Lock()
_active: set = set()
_cancel = threading.Event()


class Cancelled(Exception):
    """Raised when the user cancels a running job."""


def reset_cancel() -> None:
    _cancel.clear()


def is_cancelled() -> bool:
    return _cancel.is_set()


def request_cancel() -> None:
    """Ask the running job to stop and terminate any helper programs."""
    _cancel.set()
    with _lock:
        processes = list(_active)
    for process in processes:
        try:
            process.terminate()
        except OSError:
            pass


def stream_process(
    command: List[str],
    log_callback: Callable[[str], None],
    env: Optional[Dict[str, str]] = None,
) -> Tuple[int, List[str]]:
    """Run a command, logging each output line, and return (code, lines)."""
    if _cancel.is_set():
        raise Cancelled()
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
        creationflags=CREATE_NO_WINDOW,
    )
    with _lock:
        _active.add(process)
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                if line.strip():
                    log_callback(line)
                output_lines.append(line)
        return_code = process.wait()
    finally:
        with _lock:
            _active.discard(process)
    if _cancel.is_set():
        raise Cancelled()
    return return_code, output_lines
