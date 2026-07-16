## Riff 0.10.1 🎵

**Clickable now-playing** — tap the song title or cover to open the album/single, tap the artist name to open the artist page (when YouTube Music provides those links).

## Riff 0.10.0 🎵

**Playlist folders** (Spotify-style) — create folders from the sidebar **＋ New** menu, nest playlists inside, expand/collapse in the sidebar. Move playlists between folders from the Playlists page.
A native YouTube Music player for CachyOS / Arch Linux (GTK4 + libadwaita + mpv).

### Highlights
- Stream songs, albums, artists and playlists from YouTube Music — no ads, no account
- **Playlist folders** — organize local playlists like Spotify
- **Local AI** for AI Mix — one-click install, on-device inference (no Ollama)
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
