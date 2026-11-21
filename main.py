import json
import math
import os
import queue
import shutil
import threading
import time
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

import paths
import procutil
from processor import (
    LocalMediaProcessor,
    MUSIC_LIBRARY,
    RAW_DOWNLOADS,
    validate_playlist_name,
)

ROOT_DIR = paths.app_dir()
PLAYLISTS_FILE = ROOT_DIR / "playlists.json"
DEFAULT_INTERVAL_HOURS = 6.0
MAX_AFTER_MILLISECONDS = 2_000_000_000

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def load_playlist_state():
    if not PLAYLISTS_FILE.exists():
        return {
            "interval_hours": DEFAULT_INTERVAL_HOURS,
            "playlists": [],
            "migrated": False,
        }

    data = json.loads(PLAYLISTS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("playlists.json must contain a JSON object.")

    raw_playlists = data.get("playlists", [])
    if not isinstance(raw_playlists, list):
        raise ValueError("'playlists' must be a list.")

    playlists = []
    seen = set()
    migrated = False
    for entry in raw_playlists:
        if isinstance(entry, str):
            normalized_name = validate_playlist_name(entry)
            normalized_source = ""
            build_playlist = True
            migrated = True
        elif isinstance(entry, dict):
            raw_name = entry.get("name")
            raw_source = entry.get("source", "")
            raw_build = entry.get("build_playlist", True)
            if not isinstance(raw_name, str) or not isinstance(raw_source, str):
                raise ValueError(
                    "Each playlist entry must contain string 'name' and 'source' fields."
                )
            normalized_name = validate_playlist_name(raw_name)
            normalized_source = raw_source.strip()
            build_playlist = bool(raw_build)
            if "build_playlist" not in entry:
                migrated = True
        else:
            raise ValueError(
                "'playlists' entries must be strings or {'name', 'source', 'build_playlist'} objects."
            )

        key = normalized_name.casefold()
        if key not in seen:
            playlists.append(
                {
                    "name": normalized_name,
                    "source": normalized_source,
                    "build_playlist": build_playlist,
                }
            )
            seen.add(key)

    try:
        interval_hours = float(data.get("interval_hours", DEFAULT_INTERVAL_HOURS))
    except (TypeError, ValueError) as exc:
        raise ValueError("'interval_hours' must be a positive number.") from exc
    if not math.isfinite(interval_hours) or interval_hours <= 0:
        raise ValueError("'interval_hours' must be a positive number.")

    return {
        "interval_hours": interval_hours,
        "playlists": playlists,
        "migrated": migrated,
    }


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Local Music to iPod Nano 7G Prep")
        self.geometry("860x720")
        self.minsize(740, 600)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        self.events = queue.Queue()
        self.is_running = False
        self._closing = False
        self._scheduler_after_id = None
        self._next_check_at = None

        try:
            state = load_playlist_state()
            self.playlists = state["playlists"]
            self.interval_hours = state["interval_hours"]
            if state.get("migrated"):
                self._save_state()
        except (OSError, ValueError) as exc:
            self.playlists = []
            self.interval_hours = DEFAULT_INTERVAL_HOURS
            self.append_log(f"[Config Error] {exc}; using an empty playlist list.")
            backup = PLAYLISTS_FILE.with_name("playlists.json.broken")
            try:
                shutil.copy2(PLAYLISTS_FILE, backup)
                self.append_log(
                    f"[Config] Kept a copy of the unreadable file as {backup.name} "
                    "so it is not lost when settings are saved."
                )
            except OSError:
                pass

        self.processor = LocalMediaProcessor(log_callback=self.append_log)
        self._build_ui()
        self._refresh_playlist_list()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)
        self._schedule_auto_check()

        self.append_log(f"Raw audio folders: {RAW_DOWNLOADS}")
        self.append_log(f"Prepared library: {MUSIC_LIBRARY}")

    def _build_ui(self):
        header = ctk.CTkLabel(
            self,
            text="Prepare Local Music for iPod Nano 7G",
            font=("Segoe UI", 20, "bold"),
        )
        header.grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        instructions = ctk.CTkLabel(
            self,
            text=(
                "Place authorized audio files and matching cover art / .lrc files in "
                "raw_downloads\\<Folder Name>, or specify a Spotify URL / 'liked'. "
                "Uncheck 'Build .m3u Playlist' when downloading an album."
            ),
            anchor="w",
            justify="left",
        )
        instructions.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")

        manager = ctk.CTkFrame(self)
        manager.grid(row=2, column=0, padx=20, pady=5, sticky="ew")
        manager.grid_columnconfigure(0, weight=1)

        add_frame = ctk.CTkFrame(manager, fg_color="transparent")
        add_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        add_frame.grid_columnconfigure(0, weight=1)
        add_frame.grid_columnconfigure(1, weight=1)

        self.playlist_name_entry = ctk.CTkEntry(
            add_frame,
            placeholder_text="Folder name, e.g. Flying Mix or Album Name",
        )
        self.playlist_name_entry.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.playlist_source_entry = ctk.CTkEntry(
            add_frame,
            placeholder_text="Spotify URL, 'liked', or leave blank for local",
        )
        self.playlist_source_entry.grid(row=0, column=1, padx=(0, 8), sticky="ew")

        self.build_playlist_var = ctk.BooleanVar(value=True)
        self.build_playlist_checkbox = ctk.CTkCheckBox(
            add_frame,
            text="Build .m3u Playlist",
            variable=self.build_playlist_var,
        )
        self.build_playlist_checkbox.grid(row=0, column=2, padx=(0, 8))

        ctk.CTkButton(
            add_frame,
            text="Add Playlist Folder",
            command=self.add_playlist,
        ).grid(row=0, column=3, sticky="e")

        self.playlist_list = ctk.CTkScrollableFrame(
            manager,
            label_text="Saved local playlists & albums",
            height=130,
        )
        self.playlist_list.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.playlist_list.grid_columnconfigure(0, weight=1)

        controls = ctk.CTkFrame(self)
        controls.grid(row=3, column=0, padx=20, pady=5, sticky="ew")
        controls.grid_columnconfigure(0, weight=1)

        interval_frame = ctk.CTkFrame(controls, fg_color="transparent")
        interval_frame.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        ctk.CTkLabel(interval_frame, text="Auto-check interval (hours):").pack(
            side="left", padx=(0, 8)
        )
        self.interval_entry = ctk.CTkEntry(interval_frame, width=90)
        self.interval_entry.insert(0, str(self.interval_hours))
        self.interval_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            interval_frame,
            text="Save Interval",
            width=110,
            command=self.save_interval,
        ).pack(side="left")

        button_frame = ctk.CTkFrame(controls, fg_color="transparent")
        button_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        for column in range(3):
            button_frame.grid_columnconfigure(column, weight=1)
        self.sync_button = ctk.CTkButton(
            button_frame,
            text="Sync All Saved Playlists Now",
            command=self.sync_all_saved_playlists,
        )
        self.sync_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.cancel_button = ctk.CTkButton(
            button_frame,
            text="Cancel",
            fg_color="#b3402f",
            hover_color="#8f3224",
            state="disabled",
            command=self.cancel_sync,
        )
        self.cancel_button.grid(row=1, column=0, columnspan=3, pady=(8, 0), sticky="ew")
        ctk.CTkButton(
            button_frame,
            text="Open Raw Downloads",
            command=lambda: self.open_folder(RAW_DOWNLOADS),
        ).grid(row=0, column=1, padx=6, sticky="ew")
        ctk.CTkButton(
            button_frame,
            text="Open iPod Ready Folder",
            command=lambda: self.open_folder(MUSIC_LIBRARY),
        ).grid(row=0, column=2, padx=(6, 0), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress_bar.grid(row=4, column=0, padx=20, pady=(10, 5), sticky="ew")
        self.progress_bar.set(0)

        self.log_box = ctk.CTkTextbox(self, font=("Consolas", 12))
        self.log_box.grid(row=5, column=0, padx=20, pady=(5, 20), sticky="nsew")

    def append_log(self, text):
        self.events.put(("log", str(text)))

    def _drain_events(self):
        if self._closing:
            return
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                elif event == "done":
                    self.set_busy(False)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _refresh_playlist_list(self):
        for child in self.playlist_list.winfo_children():
            child.destroy()

        if not self.playlists:
            ctk.CTkLabel(
                self.playlist_list,
                text="No playlists saved yet.",
                anchor="w",
            ).grid(row=0, column=0, padx=8, pady=5, sticky="ew")
            return

        for row_index, item in enumerate(self.playlists):
            name = item["name"]
            source = item.get("source", "").strip()
            build_playlist = bool(item.get("build_playlist", True))
            source_display = f"Source: {source}" if source else "Source: local"

            row = ctk.CTkFrame(self.playlist_list)
            row.grid(row=row_index, column=0, padx=4, pady=3, sticky="ew")
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                row,
                text=f"{name} — {source_display} ({RAW_DOWNLOADS / name})",
                anchor="w",
            ).grid(row=0, column=0, padx=8, pady=5, sticky="ew")

            row_var = ctk.BooleanVar(value=build_playlist)
            ctk.CTkCheckBox(
                row,
                text="Build .m3u",
                variable=row_var,
                width=100,
                command=lambda playlist=name, var=row_var: self.toggle_build_playlist(
                    playlist, var.get()
                ),
            ).grid(row=0, column=1, padx=6, pady=4)

            ctk.CTkButton(
                row,
                text="Remove",
                width=80,
                command=lambda playlist=name: self.remove_playlist(playlist),
            ).grid(row=0, column=2, padx=6, pady=4)

    def _save_state(self):
        temporary = PLAYLISTS_FILE.with_suffix(".json.tmp")
        normalized_playlists = [
            {
                "name": item["name"],
                "source": item.get("source", "").strip(),
                "build_playlist": bool(item.get("build_playlist", True)),
            }
            for item in self.playlists
        ]
        data = {
            "interval_hours": self.interval_hours,
            "playlists": normalized_playlists,
        }
        try:
            temporary.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(PLAYLISTS_FILE)
        except OSError as exc:
            self.append_log(f"[Config Error] Could not save playlists.json: {exc}")
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError as cleanup_error:
                    self.append_log(
                        f"[Config Error] Could not remove temporary file: {cleanup_error}"
                    )
            return False
        return True

    def toggle_build_playlist(self, name: str, enabled: bool):
        previous = [dict(item) for item in self.playlists]
        for item in self.playlists:
            if item["name"].casefold() == name.casefold():
                item["build_playlist"] = bool(enabled)
                break
        if not self._save_state():
            self.playlists = previous
            self._refresh_playlist_list()
            return
        status = "enabled" if enabled else "disabled"
        self.append_log(f"[Playlist] .m3u generation {status} for '{name}'.")

    def add_playlist(self):
        try:
            name = validate_playlist_name(self.playlist_name_entry.get())
        except ValueError as exc:
            messagebox.showwarning("Invalid playlist name", str(exc), parent=self)
            return

        source = self.playlist_source_entry.get().strip()
        build_playlist = bool(self.build_playlist_var.get())

        folder = RAW_DOWNLOADS / name
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Folder error", str(exc), parent=self)
            return

        previous = [dict(item) for item in self.playlists]
        new_entry = {
            "name": name,
            "source": source,
            "build_playlist": build_playlist,
        }
        existing_index = next(
            (
                idx
                for idx, item in enumerate(self.playlists)
                if item["name"].casefold() == name.casefold()
            ),
            None,
        )
        if existing_index is None:
            self.playlists = self.playlists + [new_entry]
        else:
            updated = [dict(item) for item in self.playlists]
            updated[existing_index] = new_entry
            self.playlists = updated

        if not self._save_state():
            self.playlists = previous
            return

        self.playlist_name_entry.delete(0, "end")
        self.playlist_source_entry.delete(0, "end")
        self.build_playlist_var.set(True)
        self._refresh_playlist_list()
        source_info = source if source else "local"
        m3u_info = "m3u: on" if build_playlist else "m3u: off"
        self.append_log(
            f"[Playlist] Saved '{name}' ({source_info}, {m3u_info}): {folder}"
        )

    def remove_playlist(self, name):
        previous = [dict(item) for item in self.playlists]
        self.playlists = [
            playlist
            for playlist in self.playlists
            if playlist["name"].casefold() != name.casefold()
        ]
        if not self._save_state():
            self.playlists = previous
            return
        self._refresh_playlist_list()
        self.append_log(f"[Playlist] Removed saved entry (folder kept): {name}")

    def save_interval(self):
        try:
            interval = float(self.interval_entry.get().strip())
        except ValueError:
            messagebox.showwarning(
                "Invalid interval", "Enter a positive number of hours.", parent=self
            )
            return
        if not math.isfinite(interval) or interval <= 0:
            messagebox.showwarning(
                "Invalid interval", "Enter a positive number of hours.", parent=self
            )
            return

        previous = self.interval_hours
        self.interval_hours = interval
        if not self._save_state():
            self.interval_hours = previous
            return
        self._schedule_auto_check()
        self.append_log(f"[Scheduler] Auto-check interval set to {interval:g} hours.")

    def _schedule_auto_check(self):
        if self._closing:
            return
        if self._scheduler_after_id is not None:
            self.after_cancel(self._scheduler_after_id)
        self._next_check_at = time.monotonic() + self.interval_hours * 3600
        self._schedule_scheduler_wakeup()

    def _schedule_scheduler_wakeup(self):
        if self._closing or self._next_check_at is None:
            return
        remaining = self._next_check_at - time.monotonic()
        if remaining <= 0:
            self._scheduler_after_id = None
            self.append_log("[Scheduler] Checking saved playlists.")
            self.sync_all_saved_playlists(scheduled=True)
            self._next_check_at = time.monotonic() + self.interval_hours * 3600
            self._schedule_scheduler_wakeup()
            return
        delay = min(
            max(1, int(remaining * 1000)),
            MAX_AFTER_MILLISECONDS,
        )
        self._scheduler_after_id = self.after(delay, self._schedule_scheduler_wakeup)

    def sync_all_saved_playlists(self, scheduled=False):
        if self.is_running:
            self.append_log("[Info] A playlist check is already running.")
            return
        if not self.playlists:
            self.append_log("[Info] Add a local playlist folder before syncing.")
            return

        playlists_to_sync = [dict(item) for item in self.playlists]
        self.set_busy(True)
        origin = "scheduled check" if scheduled else "manual check"
        self.append_log(f"[Start] {origin}: {len(playlists_to_sync)} folder(s).")

        procutil.reset_cancel()

        def worker():
            try:
                processed = self.processor.process_playlists(playlists_to_sync)
                failed = self.processor.failed_playlists
                if failed:
                    self.append_log(
                        f"[Done with errors] {origin}: prepared {processed} new "
                        f"track(s); download failed for: {', '.join(failed)}."
                    )
                else:
                    self.append_log(
                        f"[Done] {origin}: prepared {processed} new track(s)."
                    )
            except procutil.Cancelled:
                self.append_log("[Cancelled] Stopped before finishing.")
            except Exception as exc:
                self.append_log(f"[Error] Playlist processing failed: {exc}")
            finally:
                self.events.put(("done", None))

        threading.Thread(target=worker, daemon=True).start()

    def set_busy(self, busy):
        self.is_running = busy
        self.sync_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress_bar.start()
        else:
            self.progress_bar.stop()
            self.progress_bar.set(0)

    def cancel_sync(self):
        if self.is_running:
            self.append_log("[Cancel] Stopping...")
            procutil.request_cancel()

    def open_folder(self, folder):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc), parent=self)

    def _on_close(self):
        self._closing = True
        procutil.request_cancel()
        if self._scheduler_after_id is not None:
            self.after_cancel(self._scheduler_after_id)
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()