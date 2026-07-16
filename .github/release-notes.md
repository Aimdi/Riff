## Riff 0.7.0 🎵

Spotify-style keyboard shortcuts across the app — like (Alt+Shift+B), shuffle (Alt+S), repeat (Alt+R), volume (Alt+↑/↓), page navigation (Alt+Shift+H/S/T/1), queue and sidebar toggles, mini player, and more — with a Keyboard Shortcuts overlay on Ctrl+/ or ? showing everything with keycaps. Plus a profile: click the avatar in the header to set your name and profile picture (shown Spotify-style top right, stored locally).
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
