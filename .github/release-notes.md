## Riff 0.3.0 🎵

Adds a Settings dialog (header menu → Settings): audio quality (high/medium/low, applied live), radio autoplay toggle, YouTube Music account status, and an optional Anthropic API key. With a key saved, the new **AI Mix** menu action has Claude (Opus 4.8) curate ~20 songs from your listening history and favorites, resolves them on YouTube Music, and queues them — only titles/artists are sent, the key stays local. Requires the python-anthropic package (optional).
A native YouTube Music player for CachyOS / Arch Linux (GTK4 + libadwaita + mpv).

### Highlights
- Stream songs, albums, artists and playlists from YouTube Music — no ads, no account
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
