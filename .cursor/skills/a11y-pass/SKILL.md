---
name: a11y-pass
description: Accessibility review and fix pass for Riff GTK UI. Use for labels, focus, keyboard, contrast, and target sizes.
---

# Accessibility pass

## Goal

Make a chosen flow operable without pointer reliance and clearer for assistive tech.

## Critical flows (pick one pass)

- Playback transport (play/pause, next, seek, volume)
- Search → open result → play
- Queue reorder / play next
- Settings toggles
- Lyrics tap-to-seek (keyboard equivalent?)
- Mini player controls

## Checklist

1. Every icon-only control has a tooltip and accessible name.
2. Focus visible; order matches reading order.
3. Keyboard: activate primary actions without mouse.
4. Contrast: text/icons against Pitch Black and light theme.
5. Targets: dense chrome still clickable; no hairline-only hit areas.
6. Errors/empty states are text, not color-only.
7. Destructive actions confirm or are reversible.

## Procedure

1. Walk the flow keyboard-only; note blockers.
2. Inspect widgets in `riff/ui/` for missing labels/tooltips.
3. Fix with proper GTK/Adw patterns (don’t invent custom SR hacks).
4. Re-test the same flow; record residual issues.
5. Hand visual-only tweaks to Experience; proof to Verifier.

## Output

```text
Flow: <name>
Blockers fixed:
- ...
Residual:
- ...
Files:
- ...
```
