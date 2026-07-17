# Contributing to Riff

## Development setup

```bash
sudo pacman -S python python-gobject gtk4 libadwaita mpv yt-dlp
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --all-extras --group dev
uv pip install -e ".[dev,ai]"
make pre-commit   # optional
make check
```

## Architecture rules

1. `riff/core/` must not import `gi` (secrets uses lazy optional gi).
2. Network/disk/yt-dlp on worker threads; GTK via `GLib.idle_add` / `riff.util.run_async`.
3. Never pass untrusted strings to a shell.
4. Secrets go through `riff.core.secrets`, not `settings.json`.
