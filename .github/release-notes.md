## Riff 0.4.0 🎵

AI Mix is now a refreshing playlist: each run saves the mix to a "✨ AI Mix" playlist in the sidebar (replacing the previous one) and starts playing it — and the curation prompt got a major upgrade. The model now sees your most-played songs with play counts, favorites, recent plays, followed artists, and the previous mix (which it is told never to repeat), and curates with structure: ~50% taste-adjacent, ~30% deeper cuts, ~20% discoveries, max 2 songs per artist, ordered to flow. Works with both the Anthropic and OpenAI-compatible providers.
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
