---
name: ui-polish-pass
description: Structured UI/UX polish pass for Riff GTK surfaces. Use for hierarchy, spacing, states, empty/error, motion, and perceived performance without scope creep.
---

# UI polish pass

## Goal

Improve one surface’s clarity and feel while preserving Riff’s libadwaita language.

## Scope first

Pick **one** primary surface (examples: player bar, now playing, search/discover, home, settings, mini player). List non-goals explicitly.

## Checklist

1. **Hierarchy** — one clear primary action; brand/product chrome not fighting content.
2. **Spacing** — consistent padding/margins; no accidental density spikes.
3. **States** — default / hover / pressed / focus / disabled / loading / empty / error.
4. **Overflow** — long titles truncate sanely; small windows still usable.
5. **Motion** — at most a few intentional transitions; no noisy animation.
6. **Perceived performance** — skeletons or optimistic UI where waits are real; do not fake completion.
7. **Theming** — verify Pitch Black + one accent + Snow/light if colors changed.
8. **Threading** — no new main-thread I/O.

## Procedure

1. Screenshot or describe before state (when possible).
2. Implement the minimal widget/CSS/theme edits under `riff/ui/`.
3. Manual resize pass (narrow + wide) and keyboard tab order smoke test.
4. If claiming less jank/latency, hand measurement to Performance skills.
5. Hand to Accessibility if labels/contrast/targets may have changed.

## Output

- Surface + outcome
- Files touched
- Manual checklist results
- Follow-ups for Performance / Accessibility / Verifier
