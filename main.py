import os
import subprocess
import threading
import customtkinter as ctk
from zotify_runner import ZotifyRunner, MUSIC_LIBRARY

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Spotify to iPod Nano 7G Sync")
        self.geometry("720x520")

        self.runner = ZotifyRunner(log_callback=self.append_log)
        self.is_running = False

        self.header = ctk.CTkLabel(
            self, text="Spotify → iPod Nano 7th Gen", font=("Segoe UI", 20, "bold")
        )
        self.header.pack(pady=(15, 10))

        self.url_frame = ctk.CTkFrame(self)
        self.url_frame.pack(fill="x", padx=20, pady=5)

        self.url_entry = ctk.CTkEntry(
            self.url_frame,
            placeholder_text="Paste Spotify Playlist, Album, or Track URL here...",
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=10)

        self.download_btn = ctk.CTkButton(
            self.url_frame, text="Download URL", command=self.start_url_download
        )
        self.download_btn.pack(side="right", padx=(5, 10), pady=10)

        self.btn_frame = ctk.CTkFrame(self)
        self.btn_frame.pack(fill="x", padx=20, pady=5)

        self.liked_btn = ctk.CTkButton(
            self.btn_frame,
            text="Download Liked Songs",
            fg_color="#1DB954",
            hover_color="#1aa34a",
            command=self.start_liked_download,
        )
        self.liked_btn.pack(side="left", padx=10, pady=10)

        self.sync_btn = ctk.CTkButton(
            self.btn_frame,
            text="Open iPod Ready Folder",
            command=self.open_music_folder,
        )
        self.sync_btn.pack(side="right", padx=10, pady=10)

        self.progress_bar = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress_bar.pack(fill="x", padx=20, pady=(10, 5))
        self.progress_bar.set(0)

        self.log_box = ctk.CTkTextbox(self, font=("Consolas", 12))
        self.log_box.pack(fill="both", expand=True, padx=20, pady=(5, 20))
        self.append_log("Ready. Paste a Spotify link or click 'Download Liked Songs'.")

    def append_log(self, text):
        self.after(0, self._write_log, text)

    def _write_log(self, text):
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def set_busy(self, busy):
        self.is_running = busy
        state = "disabled" if busy else "normal"
        self.download_btn.configure(state=state)
        self.liked_btn.configure(state=state)
        if busy:
            self.progress_bar.start()
        else:
            self.progress_bar.stop()
            self.progress_bar.set(0)

    def start_url_download(self):
        url = self.url_entry.get().strip()
        if not url:
            self.append_log("[Warning] Please paste a Spotify URL first.")
            return
        self._run_worker(url=url, liked=False)

    def start_liked_download(self):
        self._run_worker(url=None, liked=True)

    def _run_worker(self, url=None, liked=False):
        if self.is_running:
            return
        self.set_busy(True)

        def worker():
            try:
                self.runner.download(url=url, liked=liked)
            finally:
                self.after(0, lambda: self.set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def open_music_folder(self):
        os.makedirs(MUSIC_LIBRARY, exist_ok=True)
        subprocess.Popen(["explorer", MUSIC_LIBRARY])


if __name__ == "__main__":
    app = App()
    app.mainloop()
