---
name: measure-playback-gap
description: Measure track-change gap, time-to-first-audio, and prefetch effectiveness in Riff. Use when optimizing player/stream latency or claiming snappier skips.
---

# Measure playback gap

## Goal

Quantify delay between a user/transport action and audible playback.

## Metrics

| Metric | Definition |
| --- | --- |
| Track-change gap | Next/skip pressed → audio actually playing new track |
| Time-to-first-audio | Play on a cold stream URL → first audio |
| Prefetch hit | Whether next track used a prefetched stream (yes/no + wait ms) |

## Procedure

1. Note network conditions (approx) and whether the track is cached/downloaded vs streamed.
2. Instrument or log timestamps in `riff/core/player.py` / `riff/core/stream.py` around:
   - skip/next request
   - stream URL resolved
   - mpv load / play
   - first playback position advance (if available)
3. Sample **≥5** skips on mixed cached vs remote tracks when relevant.
4. Report median and p95 for the primary metric; keep cached vs remote separate.
5. Confirm GTK main thread is not waiting on yt-dlp (worker + idle_add pattern).
6. Remove temporary probes before merge unless gated behind diagnostics.

## Report template

```text
Metric: track-change gap (remote | cached)
Method: <log timestamps | manual stopwatch>
Baseline median / p95: <ms>
Target: <ms>
Result median / p95: <ms>
N: <count>
Prefetch: <hit rate if known>
```

## Guardrails

- Do not sacrifice gapless/crossfade correctness for a median win without noting tradeoffs.
- Separate UI-perceived responsiveness (button feedback) from audio gap; Experience may handle the former.
- Verifier must be able to reproduce with the same track class (remote/cached).
