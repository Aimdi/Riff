## Riff 0.1.3 🎵

Song actions are now always reachable: the player bar gets a full song menu (favorite, add to playlist, download, start radio, go to album/artist) for whatever is currently playing, and every queue row gets the same menu — previously these only existed on song rows in search/album/playlist lists.

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
