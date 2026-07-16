## Riff 0.2.0 🎵

Big discovery + lyrics update, inspired by Snowify:

- **Explore page**: global top songs and public playlists browsable by mood and genre — playlist recommendations without an account
- **Synced lyrics** from LRCLIB with live line highlighting and click-to-seek (falls back to YouTube Music lyrics)
- **Follow artists**: Follow button on artist pages; their newest releases appear in a "New from artists you follow" section on Home
- **Drag & drop queue reordering**
- Playlist **rename** and cover art on the playlists page
- New shortcuts: `/` focuses search, `Shift+←/→` seeks ±10s

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
