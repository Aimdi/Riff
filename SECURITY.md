# Security Policy

## Threat model

Riff is a **local desktop music player**. It runs with the privileges of the logged-in user, talks to YouTube Music via unofficial libraries (`ytmusicapi`, `yt-dlp`), and optionally sends song titles and artists only to a user-configured AI provider.

## Secrets

API keys and the ListenBrainz token are stored via the FreeDesktop **Secret Service** (libsecret) when available. If no Secret Service backend is present, they fall back to `~/.config/riff/secrets.json` with mode `0600`.

They must **not** appear in `settings.json`. On upgrade, Riff migrates leftover plaintext keys out of settings and scrubs the file.

## Reporting a vulnerability

Please report security issues privately via a GitHub security advisory or the maintainer listed on the repository profile.
