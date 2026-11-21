# Spotify to iPod Nano 7G Prep

A Windows desktop app that downloads Spotify playlists, albums and liked songs
with [spotDL](https://github.com/spotDL/spotify-downloader), converts them to
iPod-friendly MP3s (cover art, lyrics, tags) and writes a playlist file you can
import into MediaMonkey, Apple Devices or another iPod manager.

spotDL finds each track's audio on YouTube using Spotify's track information,
so quality is whatever YouTube offers, re-encoded to 320 kbps MP3.

## Requirements

- Python 3.15 (3.11 or newer should also work)
- FFmpeg (`ffmpeg.exe`), either on `PATH` or in a `tools` folder next to the app

```powershell
python -m pip install -r requirements.txt
python main.py
```

Everything the app creates (`raw_downloads`, `music_library`, `playlists.json`,
`synced_tracks.db`) is stored next to the app, so the folder can be moved
anywhere.

## Use

1. Type a folder name and a Spotify playlist / album URL (or `liked` for liked
   songs) and click **Add Playlist Folder**. Leave the source blank to prepare
   audio files you copied into `raw_downloads\<Folder Name>\` yourself
   (OGG, MP3, M4A, FLAC, WAV).
2. Click **Sync All Saved Playlists Now**. **Cancel** stops the current job and
   any spotDL / FFmpeg process it started. An optional scheduler repeats the
   check while the app is open.
3. Import `music_library` (and the playlists in `music_library\Playlists`) into
   MediaMonkey or your iPod manager. The **Open iPod Ready Folder** button opens
   it.

For each track the app writes a 320 kbps, 44.1 kHz stereo MP3 with loudness
normalization, square 500x500 JPEG cover art (from the audio, or a matching
`.jpg`/`.png` next to it) and cleaned `.lrc` lyrics as ID3v2.3 tags. Tracks with
no cover art are still converted, with a warning in the log.

Playlist files are written as `music_library\Playlists\<Folder Name>.m3u8`
(UTF-8, so accented titles import correctly), in Spotify order. Files that are
no longer in the Spotify playlist stay in the folder but are left out of the
playlist file. If a download fails, that folder is skipped and its existing
files and playlist are left untouched.

`synced_tracks.db` lets later runs skip tracks that are already prepared. Your
folders and the scheduler interval are saved in `playlists.json`; if that file
becomes unreadable the app keeps a copy as `playlists.json.broken`.

## Tests

```powershell
python -m pytest tests
```

## License

MIT License
