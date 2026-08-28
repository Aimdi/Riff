---
name: measure-startup
description: Measure Riff cold/warm start and time-to-interactive (window usable). Use when optimizing startup, import cost, or claiming faster launch.
---

# Measure startup

## Goal

Quantify **cold start** and optionally **warm start** until the main window is shown / interactive.

## Metrics

| Metric | Definition |
| --- | --- |
| Cold start | Process start → main window mapped/shown (new process) |
| Warm start | Same after a recent prior run (caches warm), if measurable |
| Import cost | Time to import `riff` / critical modules (optional microbench) |

## Procedure

1. Record environment: distro, Python, `riff` version (`python -c 'import riff; print(riff.__version__)'` when available), commit SHA.
2. Ensure a clean-ish cold start: quit all Riff instances; optionally drop FS cache only if the user allows (`sync; echo 3 | sudo tee /proc/sys/vm/drop_caches` is optional and often unavailable in CI).
3. Prefer an instrumentation approach over wall-clock of the whole shell:
   - Add temporary timed logs at process entry (`riff/app.py`) and when the main window is shown (`riff/ui/window.py` realize/map or equivalent).
   - Or wrap `make run` with `/usr/bin/time -v` for coarse RSS + elapsed (note: coarser than TTI).
4. Run **≥3** cold starts; report median and min/max.
5. If changing imports, compare `python -X importtime -c 'import riff'` (or the app entry) before/after; attach top offenders.
6. Remove temporary probes before merge unless product wants permanent diagnostics behind a flag.

## Report template

```text
Metric: cold start to window shown
Method: <logs | time -v | importtime>
Baseline (median of N): <ms>
Target: <ms>
Result: <ms>
N: <count>
Notes: <machine load, display server, etc.>
```

## Guardrails

- Do not claim TTI improvement from `/usr/bin/time` alone if the window appears much earlier than process exit.
- Keep network out of the critical path; startup should not block on yt-dlp.
- Hand proof to Verifier with reproduce steps.
