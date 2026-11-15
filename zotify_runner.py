import os
import subprocess
import sys
from io import BytesIO
from PIL import Image
from mutagen.id3 import ID3, APIC, ID3NoHeaderError

MUSIC_LIBRARY = r"F:\spotify-ipod\music_library"


class ZotifyRunner:
    def __init__(self, log_callback=None):
        self.output_dir = MUSIC_LIBRARY
        self.log_callback = log_callback or print
        os.makedirs(self.output_dir, exist_ok=True)

    def log(self, message):
        self.log_callback(str(message).rstrip())

    def download(self, url=None, liked=False):
        cmd = [
            sys.executable, "-m", "zotify",
            "--root-path", self.output_dir,
            "--codec", "mp3",
            "--export-m3u8", "True",
            "--skip-prev-downloaded", "True",
            "--bulk-wait-time", "5",
        ]

        if liked:
            cmd.append("-l")
        elif url:
            cmd.append(url.strip())
        else:
            self.log("[Error] No Spotify URL provided.")
            return False

        self.log(f"[Zotify] Starting: {' '.join(cmd)}")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            for line in process.stdout:
                if line.strip():
                    self.log(line)
            process.wait()

            if process.returncode != 0:
                self.log(f"[Error] Zotify exited with code {process.returncode}")
                return False

        except Exception as e:
            self.log(f"[Error] Failed to run Zotify: {e}")
            return False

        self.log("[Tags] Optimising MP3 tags and cover art for iPod Nano 7G...")
        self.fix_ipod_tags()
        self.log("[Done] All tracks ready in F:\\spotify-ipod\\music_library")
        return True

    def fix_ipod_tags(self):
        for root, _, files in os.walk(self.output_dir):
            for file in files:
                if not file.lower().endswith(".mp3"):
                    continue
                filepath = os.path.join(root, file)
                try:
                    tags = ID3(filepath)
                    for key in list(tags.keys()):
                        if key.startswith("APIC"):
                            apic = tags[key]
                            img = Image.open(BytesIO(apic.data)).convert("RGB")
                            img.thumbnail((500, 500))
                            buf = BytesIO()
                            img.save(buf, format="JPEG", quality=90, progressive=False)
                            tags[key] = APIC(
                                encoding=3,
                                mime="image/jpeg",
                                type=apic.type,
                                desc=apic.desc,
                                data=buf.getvalue(),
                            )
                    tags.save(filepath, v2_version=3)
                except ID3NoHeaderError:
                    pass
                except Exception as e:
                    self.log(f"[Tag Warning] {file}: {e}")
