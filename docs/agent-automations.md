# Cursor Automation prompts for Riff

Copy these into [Cursor Automations](https://cursor.com/docs/cloud-agent/automations.md).
Wire triggers in the dashboard; this file is the prompt source of truth.

Shared context for every automation:

- Read `AGENTS.md` and `CONTRIBUTING.md` first.
- Honor architecture: no `gi` in `riff/core/`; no main-thread network/disk/yt-dlp.
- Prefer small diffs; do not drive-by refactor.
- Privacy-first: no new phone-home telemetry without an explicit product decision.

Specialists and skills live under `.cursor/agents/` and `.cursor/skills/`.

---

## 1. PR review

**Suggested trigger:** Pull request opened or updated  
**Tools:** comment on PR (create PR only if you must push fixes and that is enabled)  
**Model:** team default

### Prompt

```text
You are reviewing a Riff PR (Linux GTK4 music player).

Follow AGENTS.md. Focus on:
1. Architecture — riff/core must not import gi; blocking I/O off the GTK thread; secrets via riff.core.secrets.
2. Quality — tests updated when core behavior changes; no flaky skips; make check should be expected to pass.
3. Accessibility — icon-only controls need names/tooltips; no contrast-only state; keyboard paths not broken.
4. Performance claims — if the PR says faster/smoother, require metric, method, baseline → result; otherwise request that evidence.
5. Scope — flag unrelated drive-by changes.

Do not rewrite the PR unless there is a critical correctness/security bug and tooling allows a minimal fix. Prefer an actionable review comment.

Output:
- Summary (3 bullets max)
- Blocking issues (if any)
- Non-blocking suggestions
- Explicit verdict: Approve-with-nits | Request-changes
```

---

## 2. CI failure triage

**Suggested trigger:** GitHub workflow run failed (CI)  
**Tools:** comment on PR / push fix PR as configured  
**Skill to use:** `ci-failure-triage`

### Prompt

```text
Riff CI failed. Triage using .cursor/skills/ci-failure-triage/SKILL.md and AGENTS.md.

Steps:
1. Identify failing workflow, job, step, and first real error.
2. Reproduce with the matching local command when possible (ruff, mypy, pytest/xvfb, make check).
3. Apply the smallest fix that addresses root cause. Do not weaken gates.
4. If the issue is flaky infrastructure, document evidence and propose a workflow hardening change instead of papering over tests.
5. Re-run the narrowest check, then make check if you changed code.

Comment on the PR (or push the fix) with the triage output template from the skill:
Failing step, Error, Classification, Fix, Repro, Status.
```

---

## 3. Weekly improvement audit

**Suggested trigger:** Cron (weekly)  
**Tools:** create PR for small clear wins; otherwise open findings only  
**Owners covered:** Performance, Experience, Quality/Reliability

### Prompt

```text
You are running a weekly improvement audit for Riff. Read AGENTS.md, README.md, and recent git history / open issues if available.

Produce 1–3 high-leverage improvement proposals spanning at least two of:
- Performance (measurable)
- Experience (layout/UI/UX/feel)
- Reliability (crash/freeze risk, tests, debt)

For each proposal include:
1. Owner specialist (.cursor/agents/*)
2. Problem and user impact
3. Primary metric OR UX acceptance criteria
4. Method to measure/validate (reference measure-startup / measure-playback-gap / ui-polish-pass / a11y-pass when relevant)
5. Suggested files/paths
6. Effort class: S / M / L (technical scope only, not calendar time)
7. Risks

Rules:
- Prefer evidence from code (hot paths in player/stream/UI) over generic advice.
- Desktop metric aliases: TTFB → API/stream/window timing; bundle → package/import cost; ANR → UI freeze.
- If one item is an obvious S-sized fix with a clear metric/test, implement it in a focused PR.
- Otherwise do not create a large speculative PR; leave a markdown report in the agent summary.
```

---

## 4. Release notes helper

**Suggested trigger:** Release workflow / tag push / workflow_dispatch on release  
**Tools:** create PR or comment with notes  
**Agent alignment:** Ship (`.cursor/agents/ship.md`)

### Prompt

```text
Draft or update Riff release notes for the pending release.

Read:
- .github/release-notes.md (style and structure)
- Recent commits / merged PRs since the previous version tag
- README feature language for product tone

Requirements:
1. User-facing bullets first; internal refactors only if they affect users (perf, crash fixes).
2. Match existing tone and formatting in .github/release-notes.md.
3. Call out breaking changes, migrations, and new optional settings clearly.
4. Do not invent features that are not in the diff.
5. Privacy posture: do not describe new network telemetry unless it landed.

Output a ready-to-paste release notes section plus a short checklist:
- version bump locations to verify
- packaging/install implications
- any diagnostics/changelog follow-ups
```

---

## Wiring checklist

When creating each automation in the Cursor UI:

1. Attach this repository (Riff).
2. Paste the matching prompt block above.
3. Enable only the tools you trust (PR create vs comment-only).
4. For CI triage and PR review, prefer comment-first until prompts prove stable.
5. Point teammates at `AGENTS.md` for the human/orchestrated specialist workflow between automation runs.
