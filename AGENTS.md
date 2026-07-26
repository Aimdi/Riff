# Agents guide for Riff

Riff is a native Linux music player (GTK4 + libadwaita, Python 3.11+, mpv,
YouTube Music via ytmusicapi/yt-dlp). Use this file for agent roster, handoffs,
and how to run checks.

## Run and test

```bash
# Dev setup (Arch/CachyOS-oriented)
sudo pacman -S python python-gobject gtk4 libadwaita mpv yt-dlp
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --all-extras --group dev
uv pip install -e ".[dev,ai]"

make check          # ruff + format check + mypy (core) + pytest with coverage
make lint           # ruff check
make format         # ruff format + fix
make typecheck      # mypy riff/core
make test           # pytest
make test-cov       # pytest with --cov-fail-under=60
make run            # launch the app
```

CI mirrors `make check` under Xvfb (see `.github/workflows/ci.yml`).

## Architecture rules (non-negotiable)

1. `riff/core/` must not import `gi` (secrets may lazy-import optionally).
2. Network / disk / yt-dlp work on worker threads; touch GTK only via
   `GLib.idle_add` or `riff.util.run_async`.
3. Never pass untrusted strings to a shell.
4. Secrets go through `riff.core.secrets`, not `settings.json`.

See also [CONTRIBUTING.md](CONTRIBUTING.md).

## Agent roster

The parent session is the **Orchestrator**. Specialists live in
[`.cursor/agents/`](.cursor/agents/). Skills (measurement and pass playbooks)
live in [`.cursor/skills/`](.cursor/skills/). Automation prompt templates are in
[docs/agent-automations.md](docs/agent-automations.md).

| Role | File | Owns |
| --- | --- | --- |
| Orchestrator | (parent session) | Intake, prioritization, single-owner briefs, sequencing |
| Product / Scope | `.cursor/agents/product.md` | MVP, roadmap, backlog, stories, flags, deprecation |
| Experience | `.cursor/agents/experience.md` | Layout, UI, UX, polish, motion, perceived performance |
| Performance | `.cursor/agents/performance.md` | Measurable latency, jank, startup, memory, main-thread |
| Platform / Core | `.cursor/agents/platform.md` | Core architecture, state, cache, offline, sync |
| Quality | `.cursor/agents/quality.md` | Stability, tests, regressions, maintainability |
| Accessibility | `.cursor/agents/accessibility.md` | a11y, contrast, focus, targets, SR |
| Ship / Operate | `.cursor/agents/ship.md` | CI/CD, versioning, diagnostics, changelog, packaging |
| Verifier | `.cursor/agents/verifier.md` | Before/after metrics, `make check`, reject unmeasured claims |

### Cluster → owner

- **Performance (measurable)** → Performance (+ Verifier for proof)
- **Smoothness / feel** → Experience (implementation) + Performance (numbers)
- **Layout + UI surface** → Experience
- **UX behavior** → Experience (+ Accessibility for a11y)
- **Features / scope** → Product / Scope (+ Orchestrator)
- **Quality / engineering** → Quality + Platform / Core
- **Ship / operate** → Ship / Operate

## Handoff protocol

1. **Orchestrator** turns a goal into a single-owner brief: outcome or metric,
   constraints, non-goals, and primary paths.
2. **One specialist** implements on a feature branch. Do not run Experience,
   Performance, and Platform in parallel on the same files without sequencing
   (conflicts are likely in `riff/ui/` and `riff/core/player.py`).
3. **Verifier** confirms measurement (when claimed) and runs `make check` /
   targeted tests.
4. **Ship** updates CI/changelog/diagnostics notes when user-facing or
   release-related.

### Brief template

```text
Owner: <specialist>
Goal: <one sentence>
Primary metric (if perf): <name> | method | baseline → target
Paths: <files/dirs>
Non-goals: <out of scope>
Done when: <acceptance>
```

## Measurable improvement contract

Every Performance change (and Verifier review of it) must state:

1. **Metric** (one primary) — e.g. cold start to interactive window, track-change
   gap, scroll jank / main-thread stall, RSS after load, package size
2. **Method** — timer logs, diagnostics, pytest, or a skill playbook
3. **Baseline → target → result**
4. **Non-goals**

Desktop aliases for web terms:

| Web term | Riff / desktop alias |
| --- | --- |
| TTFB / load / TTI | API/stream TTFB, window show time, time-to-first-audio |
| Bundle size | Wheel/package/installed size + startup import cost |
| FPS / jank | GTK frame timing / main-thread stall traces |
| ANR | UI freeze from main-thread I/O |
| Battery / thermal | CPU wakeups, polling, decode cost (proxies) |

## Primary code surfaces

- UI: `riff/ui/` (`theme.py`, `widgets.py`, `window.py`, player bar, now playing)
- Core: `riff/core/` (`player.py`, `stream.py`, `library.py`, `service.py`, …)
- App entry: `riff/app.py`
- Tests: `tests/`
- CI / release: `.github/workflows/`, `.github/release-notes.md`, `packaging/`
- Diagnostics: `riff/core/diagnostics.py`
