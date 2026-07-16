# Riff 🎵

A **native Linux music player** that streams from YouTube Music — no ads, no
account, no browser. Inspired by [RiPlay](https://github.com/fast4x/RiPlay)
and [Harmony Music](https://github.com/anandnet/Harmony-Music), built for
**CachyOS** (and any other Arch-based or modern Linux distro) with
**GTK4 + libadwaita**, so it looks and feels at home on the Linux desktop.

![Riff screenshot](data/screenshot.png)

## Features

- 🔍 **Search** songs, albums, artists and playlists on YouTube Music
- 🏠 **Home feed** with charts, moods and personalized-style recommendations
- 🧭 **Explore** — global top songs plus public playlists by mood and genre
- 📻 **Radio / autoplay** — when your queue runs out, related songs keep playing
- 🗒️ **Full queue control** — play next, add to queue, drag to reorder, shuffle,
  repeat (off / all / one)
- ❤️ **Favorites, history and local playlists**, stored in a local SQLite database
- 👥 **Follow artists** — their newest releases appear on your Home page
- ⬇️ **Offline downloads** (best-audio via yt-dlp); downloaded songs play from disk
- 🎤 **Synced lyrics** (LRCLIB) with live highlighting and tap-to-seek,
  falling back to YouTube Music lyrics
- 🎧 **Gapless-ready mpv audio engine** with stream prefetching for instant
  track changes
- 🖥️ **MPRIS integration** — media keys, GNOME/KDE media widgets and
  `playerctl` all work
- 🚫 No ads, no tracking, no Google account required

## Install on CachyOS / Arch

### Option A — pacman package (recommended)

```bash
# python-ytmusicapi is in the AUR; CachyOS ships paru out of the box
paru -S python-ytmusicapi

git clone https://github.com/aimdi/player.git
cd player/packaging
makepkg -si
```

### Option B — install script (no makepkg)

```bash
git clone https://github.com/aimdi/player.git
cd player
./install.sh
```

The script installs the system dependencies with pacman, sets up an isolated
virtualenv in `~/.local/share/riff-venv`, and adds a launcher plus a desktop
entry. Uninstall with:

```bash
rm -rf ~/.local/share/riff-venv ~/.local/bin/riff \
       ~/.local/share/applications/io.github.aimdi.Riff.desktop
```

### Run from source (any distro)

```bash
# Dependencies: GTK4, libadwaita, PyGObject, libmpv, plus two Python libs
sudo pacman -S python-gobject gtk4 libadwaita mpv yt-dlp   # CachyOS/Arch
pip install --user ytmusicapi yt-dlp

git clone https://github.com/aimdi/player.git
cd player
python -m riff
```

## Usage

| Action | How |
|---|---|
| Play a song + similar songs (radio) | Click any song — radio fills the queue automatically. Or song menu (⋮) → *Start Radio* |
| Play an album/playlist in order | Open it, press **Play** |
| Queue management | ⋮ menu → *Play Next* / *Add to Queue*; view the queue with the button at the bottom right |
| Favorite a song | Heart button on any song row, or the heart in the player bar |
| Create a playlist | Sidebar → *Playlists* → **New Playlist** |
| Add a song to a playlist | ⋮ menu on the song → *Add to Playlist…* |
| Download for offline | ⋮ menu → *Download* |
| Discover public playlists | Sidebar → *Explore* → pick a mood or genre |
| Follow an artist | Open the artist page → **Follow** |
| Reorder the queue | Drag a queue row onto another |
| Lyrics (synced) | Header menu → *Lyrics*; click a line to seek |
| Shortcuts | `Space` play/pause · `Ctrl+←/→` prev/next · `Shift+←/→` seek ±10s · `Ctrl+F` or `/` search · `Ctrl+Q` quit |

### Settings

Header menu → **Settings**: audio quality (high/medium/low — affects
streaming and data usage), radio autoplay, account status, and the AI Mix
API key. Stored in `~/.config/riff/settings.json`.

### AI Mix (optional)

The header menu's **AI Mix** asks an AI model to curate ~20 songs from your
listening history and favorites, finds them on YouTube Music, and queues
them. Only song titles/artists are sent; keys are stored locally. Two
provider options in Settings:

- **Anthropic (Claude)** — paste an [Anthropic API key](https://platform.claude.com/);
  uses Claude Opus 4.8. Requires the `anthropic` Python package
  (`paru -S python-anthropic` or `pip install --user anthropic`).
- **OpenAI-compatible** — any endpoint speaking the `/chat/completions`
  protocol; set base URL, key, and model. Examples: OpenAI
  (`https://api.openai.com/v1`, `gpt-4o-mini`), OpenRouter, Groq, or fully
  local via Ollama (`http://localhost:11434/v1`, key empty, model e.g.
  `llama3`) or LM Studio. No extra package needed.

### Improving recommendations & audio quality

- **Audio quality** defaults to *High*, which already picks the best audio
  stream YouTube serves (typically ~256 kbps AAC / ~160 kbps Opus). Lower
  settings save data.
- **Recommendations** improve with: the optional account connection (below),
  following artists (their releases appear on Home), your listening history
  (radio seeds from it), and AI Mix (above).

### Connect your YouTube Music account (optional)

Out of the box Riff is anonymous: generic charts on Home, no Google login.
If you *want* personalized recommendations (like RiPlay's account mode), you
can connect your account — Riff sends your browser session headers with its
requests and nothing more; there is no extra tracking, and no credentials are
stored beyond the file you create:

```bash
ytmusicapi browser --file ~/.config/riff/browser.json
```

Follow the prompts (copy request headers from an open music.youtube.com tab —
see the [ytmusicapi guide](https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html)),
then restart Riff. Home, search and radio now reflect your account's taste.
Delete the file to go back to anonymous mode.

Settings (audio quality, download folder, radio autoplay) live in
`~/.config/riff/settings.json`; the library database in
`~/.local/share/riff/library.db`; downloads default to `~/Music/Riff`.

## Architecture

```
riff/
├── app.py            Adw.Application, global shortcuts
├── mpris.py          MPRIS2 D-Bus server (media keys, playerctl)
├── config.py         XDG paths + JSON settings
├── core/             UI-independent — fully unit-tested
│   ├── api.py        ytmusicapi wrapper → typed models
│   ├── models.py     Track / Album / Artist / Playlist dataclasses
│   ├── stream.py     yt-dlp stream-URL resolver with TTL cache
│   ├── player.py     libmpv audio engine (ctypes, no extra deps)
│   ├── queue.py      shuffle / repeat / play-order logic
│   ├── service.py    PlaybackService: queue + engine + radio autoplay
│   ├── library.py    SQLite favorites / history / playlists / downloads
│   └── downloader.py offline downloads
└── ui/               GTK4 + libadwaita widgets and pages
```

Playback pipeline: `ytmusicapi` finds the music → `yt-dlp` resolves a direct
audio stream URL (cached, prefetched for the next track) → `libmpv` plays it.

## Development

```bash
python -m pytest tests/          # unit + libmpv integration tests
python -m riff                   # run the app
```

## License

[GPL-3.0-or-later](LICENSE). Riff is an independent open-source project, not
affiliated with or endorsed by Google/YouTube. It uses publicly available
APIs via [ytmusicapi](https://github.com/sigma67/ytmusicapi) and
[yt-dlp](https://github.com/yt-dlp/yt-dlp); use it in accordance with the
laws and terms applicable to you.
