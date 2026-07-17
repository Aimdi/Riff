## Riff 0.20.0 🎵

**Browse lives under Search now — like Spotify mobile.** The sidebar is down to one discovery entry: open Search and, while the box is empty, you get the Browse view with the Discover / Charts & Moods switcher. Start typing and results take over (with the Songs/Albums/Artists/Playlists filters); clear the box and Browse comes right back. Also fixes Browse loading eagerly at startup — it now waits until you actually open it.

### What’s new since 0.8.0

#### Video (0.12)
- **In-app music video** plays in the cover-art slot (GStreamer + muted video; mpv keeps audio)
- Toggle video from the now-playing cover when a video stream is available

#### Playlist folders (0.10–0.11)
- **Spotify-style folders** — create from sidebar **＋ New**, nest playlists, expand/collapse
- Drag-and-drop playlists into folders; move from the Playlists page
- **Colored folder badges** with custom emoji; right-click folder menu
- Flat badge style aligned with desktop folder icons

#### Home & AI (0.9–0.11)
- **For you** strip on Home — AI picks when a provider/local model is ready, else smart radio from history
- **Local AI** — in-process GGUF (no Ollama); model picker (Qwen, Llama, Gemma) with a recommended default
- Clickable now-playing title/cover → album; artist name → artist page

#### Library & UX (0.8.1–0.8.2)
- **Add** on public playlists — one-click local snapshot
- Icons that stay visible on CachyOS / elementary / Breeze dark themes
- Stable player-bar height for video thumbnails

### Highlights
- Stream songs, albums, artists and playlists from YouTube Music — no ads, no account
- Playlist folders, local AI Mix, in-app video in the cover slot
- Radio autoplay, queue (shuffle/repeat), favorites, history, offline downloads
- Lyrics, MPRIS2, stream prefetching

### Install on CachyOS / Arch

```bash
paru -S python-ytmusicapi          # AUR dependency
git clone https://github.com/Aimdi/Riff.git
cd Riff/packaging && makepkg -si
```

or without makepkg: `./install.sh`

Update an existing install: `riff-update`

The attached wheel can also be installed directly (system deps: `gtk4`, `libadwaita`, `python-gobject`, `mpv`; video needs GStreamer gtk4paintablesink plugins):

```bash
pip install --user riff_player-*.whl ytmusicapi yt-dlp
```
