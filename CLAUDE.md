# CLAUDE.md

Feed Me: share an article from iOS, get it narrated (OpenAI TTS) into a private
podcast RSS feed. FastAPI, server-rendered Jinja2, filesystem-as-database, on
Fly.io. See `README.md` for the full architecture and route list.

## Commands

```bash
uv run pytest                 # full test suite (no network; fake http/openai)
uv run pytest tests/test_app.py -k share -v   # focused
# Run locally (/data is read-only on macOS, so override the data dir):
FEED_ME_DATA_DIR=/tmp/feedme OPENAI_API_KEY=sk-test-dummy APP_BASE_URL=http://localhost:8000 \
  uv run uvicorn app:app --reload
# Deploy (this exact invocation):
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

## Conventions

- **Workflow:** features go brainstorm → spec (`docs/superpowers/specs/*.html`)
  → plan (`docs/superpowers/plans/*.md`) → TDD implementation. Each release gets
  a `CHANGELOG.md` entry and a `vX.Y` git tag. Work on `master`.
- **TDD:** write the failing test first. Tests never hit the network; use the
  `fake_http` / `fake_openai` fixtures and the `client` fixture (which points
  `DATA_DIR` at a temp dir per test). `client` uses `base_url="https://testserver"`
  so the `Secure` session cookie round-trips.
- **Identity:** the `/u/<secret>` URL is the whole account (no login). `/share`
  identifies the user by the `fm_session` cookie, set on every feed-page view.
  Never log or expose the raw secret.
- **Copy:** no em-dashes in user-facing text (owner preference); the middot `·`
  is fine. Grep for `—` before shipping template changes.

## Gotchas

- Importing `app`/`ingest` instantiates `OpenAI()` at module load, so
  `OPENAI_API_KEY` must be set in the environment even to import (tests set a
  dummy via `conftest.py`).
- Analytics (`analytics.py`) lives in `/data/_analytics/`. Any code that
  enumerates feeds under `/data` must filter to directories; never assume every
  entry is a feed dir.
- `analytics.track()` must never raise (it's on the request path); `summary()` /
  `all_events()` may raise (admin-only). Attribute analytics by
  `feed_hash(secret)`, never the raw secret.
- `scripts/gen_*.py` regenerate committed assets in `static/` (cover, welcome
  audio, favicon, OG image). Production never runs them; commit script + output
  together.
- Deploys sometimes print a "not listening on 0.0.0.0:8000" warning; it's a
  benign Fly timing artifact; verify with `curl https://feed-me.xyz/healthz`.
- The agent API (`POST/GET/DELETE /u/<secret>/episodes*`) authenticates by the
  path secret only: never read or set the session cookie there, and keep
  its errors as `{"error", "message"}` JSON (the POST parses its body by
  hand because a Pydantic model would 422 instead of the documented 400).
  DELETE returns `{"slug", "status": "deleted"}` and 404s an unknown slug.
- `templates/agents.md` is substituted with plain `.replace("{base}", ...)`,
  not Jinja (autoescape mangles the JSON examples) and not `str.format`
  (the JSON braces break it).
- GA4 lives in `templates/_ga.html`. `page_location` / `page_referrer` must be
  masked on any page whose URL can contain `/u/<secret>` (settings sets
  `ga_mask_location` before the include). Never add the GA partial to a new
  secret-bearing page without the mask; the raw secret must never reach Google.
