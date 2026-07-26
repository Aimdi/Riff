---
name: ci-failure-triage
description: Triage Riff GitHub Actions CI failures (ruff, mypy, pytest, coverage). Use on red CI or when fixing a broken PR check.
---

# CI failure triage

## Goal

Identify the failing job/step, root-cause it, and apply the smallest fix (or a clear handoff).

## CI map

Workflow: `.github/workflows/ci.yml` (quality job)

Typical steps:

1. System libs + uv + Python
2. `uv sync` / editable install
3. `ruff check`
4. `ruff format --check`
5. `mypy riff/core`
6. `xvfb-run pytest` with coverage gate on `riff/core` (≥60%)

Local mirrors: `make lint`, `make format`, `make typecheck`, `make test-cov`, `make check`.

## Procedure

1. Open the failed run; capture **job**, **step**, and **first error** (not only the last).
2. Reproduce locally with the same command when possible.
3. Classify:
   - **Style** → ruff/format
   - **Types** → mypy in core
   - **Test correctness** → pytest assertion/traceback
   - **Coverage** → new core code untested
   - **Environment** → missing system libs / xvfb / network
4. Fix the root cause; avoid `# type: ignore` / skips unless justified and documented.
5. Re-run the narrowest command, then `make check` before declaring done.
6. If the failure is flaky infra, document evidence and hand to Ship for workflow hardening.

## Output

```text
Failing step: <name>
Error: <one-liner>
Classification: style | types | test | coverage | env
Fix: <summary>
Repro: <command>
Status: fixed | needs-handoff (<owner>)
```
