# One-Page Merge (v3.34) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the decided design package (spec: `docs/superpowers/specs/2026-08-26-session-page-directions.html`, "C + O1 with O2 floor, one page"): the feed page `/u/<secret>` becomes the whole experience and the separate `/collab` page goes away.

**Architecture:**
- `settings.html` reworked: h1 "Your feed" + episode/voice subline; a **Listen card** (`#listen-card`: Apple Podcasts, Overcast, Pocket Casts, Copy RSS, plus a hidden `#agent-copied` line) that is the hero on a fresh feed (`not setup_done`) and sits below the episodes hero afterward; iOS setup **always** folded under "Setup & sharing"; a bottom **agent trace** (`#agent-trace` one-liner + `#agent-history-btn` toggling `#agent-log`), hidden until an agent acts. Agent chrome (pill, explainer, prompt chips) removed; chips also removed from `_setup_instructions.html`.
- `GET /u/{secret}/collab` becomes a 301 to `/u/{secret}`; `templates/collab.html` deleted.
- `webmcp.js`: native agent mode targets the trace ids; the `/collab` hop and path handling removed (`create_feed` navigates to the feed page); new **`help_subscribe`** tool (flash the Listen card, best-effort clipboard copy of the RSS link, reveal `#agent-copied` only on success, return per-app links + relay instructions); `create_feed`'s result names `help_subscribe` as the next step; arrival-from-create flashes the Listen card.
- Docs: AGENTS.md tool list + example prompt for `help_subscribe`; README rows; CHANGELOG v3.34 + tag.

**Tech Stack:** FastAPI, Jinja2, pytest (`uv run python -m pytest`), plain browser JS.

---

## Tasks

- [ ] **Task 1 · Tests first.** Rework `tests/test_webmcp.py`: collab tests → a 301-redirect test; toolset gains `help_subscribe` (TOOL_NAMES drives the JS and AGENTS.md checks); JS contract gains `agent-trace-text` / `agent-copied` / clipboard; create_feed result names `help_subscribe`; settings page: Listen hero before episodes on a fresh feed and after them once shared, "Setup &amp; sharing" always present, trace markup present, prompt chips gone. Update the two layout tests in `tests/test_app.py` to the new hierarchy.
- [ ] **Task 2 · Template + route.** Rework `settings.html` (+ `_setup_instructions.html` chip removal); collab route → `RedirectResponse(301)`; delete `templates/collab.html`.
- [ ] **Task 3 · webmcp.js.** Trace-native agent mode, `/collab` removal, `help_subscribe`, result-text choreography. `node --check`, em-dash grep.
- [ ] **Task 4 · Docs + release.** AGENTS.md, README, CHANGELOG v3.34, tag, deploy, verify live.

**Copy constraint:** no em-dashes anywhere new. **Clipboard honesty:** `#agent-copied` renders only after a successful `writeText`; the Copy RSS button is the always-available fallback.
