## Riff 0.9.0 🎵

**Local AI Mix** — Settings → AI Mix → Provider: **Local (recommended)**. One Install button downloads Ollama (if needed) and Riff’s chosen model, **Qwen 2.5 3B** (~2 GB): small, private, no API key. Cloud Claude / OpenAI-compatible options remain.
A native YouTube Music player for CachyOS / Arch Linux (GTK4 + libadwaita + mpv).

### Highlights
- Stream songs, albums, artists and playlists from YouTube Music — no ads, no account
- **Local AI** for AI Mix — install with one click, fully offline after download
- **Add** button on public playlists — one click to copy them into your local library
- Icons that stay visible on CachyOS / elementary / Breeze dark themes
- Radio autoplay: when the queue runs out, related songs keep playing
- Queue with shuffle, repeat (off/all/one), play-next and add-to-queue
- Favorites, listening history and local playlists (SQLite)
- Offline downloads via yt-dlp
- Lyrics for the current song
- MPRIS2 integration: media keys, GNOME/KDE widgets, `playerctl`
- Stream prefetching for instant track changes

### Install on CachyOS / Arch

```bash
paru -S python-ytmusicapi          # AUR dependency
git clone https://github.com/aimdi/player.git
cd player/packaging && makepkg -si
```

or without makepkg: `./install.sh`

The attached wheel can also be installed directly (system deps: `gtk4
libadwaita python-gobject mpv`):

```bash
pip install --user riff_player-*.whl ytmusicapi yt-dlp
```
