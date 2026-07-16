## Riff 0.5.0 🎵

Six new features: **ListenBrainz scrobbling** (Settings → token; standard half-or-4-minutes rule), **"Never Play This"** in every song menu (banned songs are filtered from radio and AI Mix; manage them in the new Disliked sidebar page), **daily AI Mix auto-refresh** (Settings toggle; refreshes in the background on first launch each day), a **Mini Player** window (header menu), **Local Files** (index a folder from Settings; "Artist - Title.ext" naming gets artist tags), and a **Stats page** (plays, hours, top songs/artists, 14-day activity).
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
