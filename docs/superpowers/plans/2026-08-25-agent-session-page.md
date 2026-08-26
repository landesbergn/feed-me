# Agent Session Page (v3.31) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an agent drives a feed through WebMCP, the person lands on `/u/<secret>/collab`: a page built for watching the collaboration (live status strip, persisted activity log, live episodes, prompt chips), instead of the setup-oriented settings page.

**Architecture:** One new route + template (`collab.html`, reusing `_episodes_section.html`, the 3s partial poll, and the pending ticker). `static/webmcp.js` learns the `/collab` path, renders agent mode natively there (status strip + sessionStorage-persisted log instead of the injected banner), navigates to collab from `create_feed`, and hops there after the first completed tool call on the classic feed page. No new API endpoints, caps, or storage changes.

**Tech Stack:** Python 3, FastAPI, Jinja2, Starlette `TestClient`, pytest; plain browser JS. Run tests with `uv run python -m pytest` (the bare `pytest` entrypoint has a stale shebang).

**Spec:** `docs/superpowers/specs/2026-08-25-agent-session-page.html`

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `app.py` | Modify (route after `settings`) | `GET /u/{secret}/collab` |
| `templates/collab.html` | New | The agent-session view |
| `static/webmcp.js` | Modify | `/collab` path, native agent mode + log, transitions |
| `tests/test_webmcp.py` | Modify (append) | Route + script contract tests |
| `README.md` | Modify | Route row |
| `CHANGELOG.md` | Modify | v3.31 entry (+ tag) |

**Conventions:** no em-dashes in user-facing copy; GA on a secret-bearing page only with `ga_mask_location`; never track the raw secret; cookie set exactly as `settings` does.

---

## Task 1: Failing tests

- [ ] Append to `tests/test_webmcp.py`: collab page serves session markup (`You + your agent`, `agent-log`, `agent-status-text`, `episodes-section`, webmcp include, prompt chips, exit link, no em-dash); sets `fm_session` cookie; 404 on unknown secret; GA masked to `/u/_`; script contract (`/collab`, `agent-log`, `fmAgentLog`, `agent-status-text`).
- [ ] Run: expect failures (route 404, script lacks strings).

## Task 2: Route + template

- [ ] `app.py`: `collab(request, secret)` mirroring `settings` (404, `_track("page_view", path="collab")`, episodes[:30] with `when`, `feed_url` / `feed_host_and_path` / `base_url`, `set_session_cookie`), rendering `collab.html`.
- [ ] `templates/collab.html`: masked GA include; header + status pill; activity card (`#agent-log` + `#log-empty`); episodes card (`#episodes-section` include + poll script with the URL built from the secret, + pending ticker); prompt-chip card (v3.29 prompts, click-to-copy); listen card (Apple Podcasts + copy RSS); exit link; `/webmcp.js` deferred. Two-column grid ≥720px.

## Task 3: webmcp.js

- [ ] Path regex `^\/u\/([A-Za-z0-9_-]+)(\/collab)?\/?$` with `onCollab`; `refreshEpisodes` uses `"/u/" + secret + "/episodes_partial"`.
- [ ] Log: `fmAgentLog` in sessionStorage (cap 50, skip consecutive duplicates), `renderLog()` newest-first into `#agent-log`, restore on load. `agentMode(message, quiet)`: native `#agent-status-text` when present, else the injected banner; logs unless quiet. `get_episode_status` is quiet.
- [ ] Transitions: `create_feed` navigates to `page + "/collab"`; on the classic feed page the first successful call schedules `location.assign(base + "/collab")` (700ms, once).
- [ ] `node --check`, em-dash grep, full suite green.

## Task 4: Docs + release

- [ ] README route row; CHANGELOG v3.31; commit; tag `v3.31`; deploy; verify `/healthz` and a live collab page string.

## Self-Review

Route mirrors `settings` exactly on auth/cookie/tracking; log renders only fixed script strings (no tool input in the DOM); navigation never interrupts an in-flight call; all v3.28-v3.30 test pins remain valid.
