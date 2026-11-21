# Local Music Prep for iPod Nano 7G

A Windows desktop utility that prepares local audio files for manual import into
MediaMonkey, Apple Devices, or another iPod manager. It does not download audio
from Spotify or run external downloader commands.

## Requirements

- Python 3.10 or newer
- FFmpeg with `ffmpeg.exe` available on `PATH`
- Python packages in `requirements.txt`

Install the Python packages and start the app:

```powershell
python -m pip install -r requirements.txt
python main.py
```

Check that FFmpeg is available with `ffmpeg -version`.

## Prepare a playlist

1. Copy audio files you are authorized to use into
   `F:\spotify-ipod\raw_downloads\<Playlist Name>\`. Supported formats are
   OGG, MP3, M4A, FLAC, and WAV.
2. Provide cover art embedded in the audio or as a matching image alongside the
   track (`<track>.jpg`, `.jpeg`, `.png`, `.webp`, or `cover.jpg`,
   `cover.jpeg`, `cover.png`, or `folder.jpg`).
3. Optionally add a matching `<track>.lrc` lyrics file.
4. Add the playlist folder in the app, then click **Sync All Saved Playlists
   Now**. The optional scheduler checks saved folders while the app is running.

The app writes normalized 320 kbps CBR, 44.1 kHz stereo MP3s to
`F:\spotify-ipod\music_library\<Playlist Name>\`, applies loudness
normalization, embeds square 500x500 JPEG artwork and cleaned LRC lyrics as
ID3v2.3 tags, and creates a relative-path playlist at
`F:\spotify-ipod\music_library\Playlists\<Playlist Name>.m3u`.

Tracks without discoverable cover art are skipped with an error in the log.
Tracks without an LRC file are processed without a lyrics frame.

The database at `synced_tracks.db` skips unchanged source files on later runs.
The **Open iPod Ready Folder** button opens the prepared library; importing it
onto the iPod is done with your chosen media manager.

Playlist names and the auto-check interval are saved locally in
`playlists.json`. Raw downloads, generated playlists, and the database are
excluded from version control.
