# Feed Me

Your articles, read to you in a private podcast feed. Share an article from your
phone; Feed Me fetches it, narrates it with OpenAI TTS, and drops it into a
private RSS feed you subscribe to in any podcast app.

Live at **[feed-me.xyz](https://feed-me.xyz)**.

## How it works

1. **Create a feed.** `POST /create` mints a private, unguessable feed at
   `/u/<secret>` and sets a long-lived first-party cookie (`fm_session`) tying
   this browser to that feed. The secret URL *is* the account; bookmark it.
2. **Install one generic iOS Shortcut** (one tap, no copy/paste). It takes a
   shared article URL, URL-encodes it, and opens
   `https://feed-me.xyz/share?url=<article>` in your browser.
3. **`/share` identifies you by the cookie** (not by anything baked into the
   Shortcut), writes a pending episode, and kicks off ingest in a background
   thread. The page shows a live progress bar that polls `/share/status` until
   the audio is ready.
4. **Ingest** (`ingest.py`): fetch the article (`httpx` + `readability-lxml`),
   chunk the text at sentence boundaries, synthesize each chunk with OpenAI TTS
   (`tts-1`) in parallel, concatenate the MP3s, and write the episode.
5. **Subscribe** to `/u/<secret>/feed.xml` in Apple Podcasts, Overcast, Pocket
   Casts, etc. (Spotify is not supported; it rejects arbitrary RSS.)

There is no database and no login. Each feed is a directory under the data
volume: `/data/<secret>/` holds `settings.json` plus one `<slug>.json` (+
`<slug>.mp3`) per episode. The secret is the credential.

## Routes

| Route | Purpose |
|-------|---------|
| `GET /` | Landing page |
| `POST /create` | Mint a new feed, seed the welcome episode, set the session cookie, redirect to `/u/<secret>` |
| `GET /u/{secret}` | The feed's home/settings page; refreshes the session cookie. Leads with the episodes table once a real article has been shared, else with setup instructions |
| `GET /share?url=` | Capture endpoint hit by the Shortcut; cookie-identified. Renders a live "adding…" → "added"/"failed" page |
| `GET /share/status?slug=` | JSON status for one episode, polled by the `/share` page (cookie-authed) |
| `GET /u/{secret}/episodes_partial` | Episode table fragment, polled every 3s by the settings page |
| `POST /u/{secret}/voice` | Change the TTS voice (shimmer / alloy / nova / echo) |
| `POST /u/{secret}/rotate` | Rotate the secret (invalidates the old URL) |
| `GET /u/{secret}/feed.xml` | The RSS feed |
| `GET /u/{secret}/audio/{slug}.mp3` | Episode audio |
| `GET /admin/stats?token=` | Analytics dashboard (token-gated, 404 without the right `STATS_TOKEN`) |
| `GET /admin/export?token=` | Analytics JSON dump (summary + raw events) |
| `GET /healthz`, `/cover.jpg`, `/og.png`, `/favicon.ico`, `/favicon-32.png`, `/apple-touch-icon.png` | Health, cover art, share image, icons |

## Modules

- **`app.py`**: all FastAPI routes, the session cookie, and analytics wiring.
- **`ingest.py`**: article fetch, text chunking, parallel TTS, MP3 assembly.
- **`storage.py`**: the filesystem "database": users, episodes, settings.
- **`rss.py`**: renders the RSS feed (episode show notes link to the original
  article and back to the feed page).
- **`analytics.py`**: self-hosted SQLite event store (see below).
- **`templates/`**: Jinja2: `landing`, `settings`, `share`, `admin_stats`,
  `feed.xml`, and the `_episodes_section` / `_setup_instructions` partials.
- **`scripts/`**: one-off asset generators (`gen_cover`, `gen_welcome`,
  `gen_favicon`, `gen_og`); never run in production, outputs are committed to
  `static/`.

## Analytics

Self-hosted, privacy-preserving, no third party. Events
(`page_view`, `feed_created`, `article_shared`) are written to a SQLite DB at
`/data/_analytics/analytics.db` (its own subdir so the `/data/<secret>/` feed
level stays pure). Each event is attributed by a **one-way `sha256(secret)[:12]`
hash, never the raw secret**, so the analytics can never reveal a private feed
URL. `article_shared` events also store the article URL + title. Writes are
fire-and-forget and can never break a page render. View at `/admin/stats?token=`.

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `FEED_ME_DATA_DIR` | `/data` | Root of the filesystem store |
| `APP_BASE_URL` | `http://localhost:8000` | Public base URL (used in feed/share URLs and to gate the `Secure` cookie flag) |
| `OPENAI_API_KEY` | (required) | Required for TTS |
| `SHORTCUT_ICLOUD_URL` | placeholder | iCloud link to the generic "Feed Me" Shortcut |
| `STATS_TOKEN` | unset | Required to access `/admin/*`; unset ⇒ those routes 404 |

## Develop

```bash
uv sync                       # install deps (incl. the dev group: pytest, pillow)
uv run pytest                 # run the test suite
# Run locally (needs a writable data dir + a dummy/real OpenAI key):
FEED_ME_DATA_DIR=/tmp/feedme OPENAI_API_KEY=sk-... APP_BASE_URL=http://localhost:8000 \
  uv run uvicorn app:app --reload
```

Tests use a fake HTTP client and fake OpenAI client (see `tests/conftest.py`),
so they make no network calls. The `client` fixture points `DATA_DIR` at a temp
dir, so each test gets an isolated filesystem store and analytics DB.

## Deploy

Hosted on Fly.io (app `feed-me-noah-willow-grove-8052`, region `sjc`, a single
machine with a persistent volume mounted at `/data`).

```bash
# Set secrets once (and on rotation):
fly secrets set OPENAI_API_KEY=... SHORTCUT_ICLOUD_URL=... STATS_TOKEN=... \
  --app feed-me-noah-willow-grove-8052

# Deploy:
fly deploy --app feed-me-noah-willow-grove-8052
```

`APP_BASE_URL` and `FEED_ME_DATA_DIR` are set in `fly.toml`. Releases are tagged
(`vX.Y`); see `CHANGELOG.md`.

## Design docs

Per-feature specs and implementation plans live in
`docs/superpowers/specs/` and `docs/superpowers/plans/`.

## License

MIT — see [`LICENSE`](LICENSE).
