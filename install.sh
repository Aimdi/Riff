#!/usr/bin/env bash
# Quick install for CachyOS / Arch without makepkg.
#
# Installs system dependencies with pacman, then puts Riff in an isolated
# venv under ~/.local/share/riff-venv with a `riff` launcher in ~/.local/bin.
set -euo pipefail

if ! command -v pacman >/dev/null; then
    echo "This installer targets CachyOS / Arch Linux (pacman not found)." >&2
    echo "On other distros: install gtk4, libadwaita, python-gobject, mpv," >&2
    echo "then run: pip install --user ." >&2
    exit 1
fi

echo "==> Installing system dependencies (needs sudo)…"
sudo pacman -S --needed --noconfirm \
    python python-gobject gtk4 libadwaita mpv yt-dlp python-pip

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
VENV="$APP_DIR/riff-venv"
BIN_DIR="$HOME/.local/bin"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Creating virtualenv at $VENV…"
# --system-site-packages lets the venv use the distro's PyGObject/GTK bindings.
python -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
# PyGObject comes from the system (python-gobject) via --system-site-packages;
# install Riff itself with --no-deps so pip never tries to compile it.
"$VENV/bin/pip" install --quiet ytmusicapi yt-dlp
"$VENV/bin/pip" install --quiet --no-deps "$SRC_DIR"

echo "==> Installing launcher, desktop entry and icon…"
mkdir -p "$BIN_DIR" \
    "$APP_DIR/applications" \
    "$APP_DIR/icons/hicolor/scalable/apps"
ln -sf "$VENV/bin/riff" "$BIN_DIR/riff"
cp "$SRC_DIR/data/io.github.aimdi.Riff.desktop" "$APP_DIR/applications/"
cp "$SRC_DIR/data/io.github.aimdi.Riff.svg" \
    "$APP_DIR/icons/hicolor/scalable/apps/"
# Point Exec at the absolute launcher path in case ~/.local/bin isn't in PATH.
sed -i "s|^Exec=riff$|Exec=$BIN_DIR/riff|" \
    "$APP_DIR/applications/io.github.aimdi.Riff.desktop"
update-desktop-database "$APP_DIR/applications" 2>/dev/null || true
gtk-update-icon-cache "$APP_DIR/icons/hicolor" 2>/dev/null || true

echo
echo "Done! Launch with:  riff   (or find “Riff” in your app menu)"
echo "If 'riff' is not found, add ~/.local/bin to your PATH."
