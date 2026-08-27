# The Producer (v3.36) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Spec:** `docs/superpowers/specs/2026-08-26-the-producer.html`. Tests are the contract; run with `uv run python -m pytest`.

## Tasks

- [ ] **T1 · Storage.** Generalize `_pending_via` into a prior-record read so `note` survives finalization; `note` params on the three writers; `list_requests` / `add_request` / `complete_request` over `<user>/inbox/requests.json` (caps 500 chars, 20 open; open-text dedupe). Tests in the new `tests/test_producer.py`.
- [ ] **T2 · RSS.** Description leads with `Producer's note:` when present; ends with the two feedback links (`{feed_page}/feedback?slug=..&v=more|less`), HTML and text variants. Tests extend `tests/test_rss.py` patterns inside `test_producer.py`.
- [ ] **T3 · Routes.** `note` through `POST /episodes` (400 on bad type or >300 chars); `GET/POST /u/{secret}/requests`, `POST .../requests/{rid}/complete`, `GET .../requests_partial`, `GET .../feedback`. Form POST redirects 303; JSON returns 201. Agent-contract errors.
- [ ] **T4 · Page.** "For your producer" card (`#requests-section` include + partial), episode-row note line, CSS.
- [ ] **T5 · webmcp.js + AGENTS.md.** `note` in the add schemas; `get_requests` / `complete_request` tools with refresh/flash reactions; producer copy in the trace strings; AGENTS.md producer framing, requests API docs, prompts. TOOL_NAMES grows to 11.
- [ ] **T6 · Release.** README rows, CHANGELOG v3.36, tag, deploy, live verify (feed.xml note, feedback tap, requests API).
