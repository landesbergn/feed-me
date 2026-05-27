# Changelog

## v1.6 — 2026-05-27

Episode metadata + Apple Podcasts compatibility:

- Pending rows now show the article's real title (via a quick `<title>` fetch at /ingest time, before TTS runs). Falls back to "Loading from <hostname>…" if the fetch fails. The misleading "(couldn't extract article)" is now reserved for actual failures.
- Every RSS item carries a `<description>` and `<itunes:summary>` — first ~200 chars of the article body for ready episodes, source URL for pending, hand-written for the welcome.
- Apple Podcasts compatibility:
  - Real byte-count `length` attribute on every `<enclosure>` (was `length="0"` — Apple often rejects)
  - `<atom:link rel="self">` added to channel
  - `<itunes:type>episodic</itunes:type>` added to channel
  - "Add to Apple Podcasts" button uses `podcast://` (singular — Apple's documented scheme; plural `podcasts://` was wrong)
- Spec: `docs/superpowers/specs/2026-05-27-episode-metadata-and-apple-podcasts.html`

## v1.5 — 2026-05-27

First-run smoothness:

- Pre-seeded "Welcome to Feed Me" episode (~30s AI-narrated MP3) on every new feed, so podcast apps can subscribe even before the user has shared any articles
- Settings page now polls `/u/<secret>/episodes_partial` every 3s while tab is visible — new shares show up as "Pending" then "Ready" without manual refresh (~6s total perceived latency)
- Episode section extracted to a Jinja partial so the polling endpoint and the main settings render share one source of truth
- Spec: `docs/superpowers/specs/2026-05-26-welcome-episode-and-live-updates.html`

## v1.4 — 2026-05-26

Feed cover art + richer description so every user's feed looks like a real podcast in Apple Podcasts / Overcast / etc.:

- Sunset cover art (warm gradient + play glyph + bold "FEED ME" wordmark), 3000×3000 JPG, served from `/cover.jpg`
- Channel description updated to "Your personal podcast of articles you've saved with Feed Me."
- New `<itunes:summary>` (same text) and `<itunes:image>` (channel-level) in the RSS feed
- Pillow added as a dev-only dependency (one-time `gen_cover.py` script generates the JPG; production never runs Pillow)
- Spec: `docs/superpowers/specs/2026-05-26-feed-metadata-and-cover-art.html`

## v1.3 — 2026-05-26

Settings page redesigned for friend-onboarding:

- Three-phase layout: Set up (Install Shortcut + Subscribe in podcast app, paired buttons) → Share an article (3 numbered steps with inline iOS Share icon SVG and "Feed Me" rendered as a kbd-style tag) → Recent episodes (3-column table with Ready / Pending / Failed status chips and friendly "When" column)
- Voice picker, Ingest URL, and Rotate moved into a collapsible Settings drawer at the bottom (closed by default)
- Backend gains a "pending" episode state: `ingest.process` now writes a pending stub before fetch and promotes it to ready/failed on completion, so just-shared articles show up on the next refresh instead of vanishing into the void
- `app.relative_time` helper buckets timestamps into "just now / N min ago / N h ago / N d ago / YYYY-MM-DD"
- `storage.write_episode` and `write_failed_episode` gain an optional `slug` param for in-place promotion
- Spec: `docs/superpowers/specs/2026-05-26-settings-page-redesign.html`

## v1.2 — 2026-05-26

Friends can self-serve end-to-end:

- Canonical iOS Shortcut now shared via iCloud with an Import Question that prompts the installer for their own ingest URL
- `SHORTCUT_ICLOUD_URL` Fly secret set to the real iCloud link
- "Install Shortcut" button on settings page now auto-copies the friend's ingest URL to clipboard before opening the iCloud install card — so iOS's Paste suggestion appears above the keyboard during the Import Question prompt
- Step 3's "Copy ingest URL" is now a manual fallback, captioned accordingly
- Investigated and ruled out per-user server-generated shortcuts: iOS no longer permits installing unsigned shortcuts ("Importing unsigned shortcut files is not supported")

## v1.1 — 2026-05-26

Landing page redesign + custom domain:

- Minimal Linear-style hero, privacy-first headline (`Your articles, read to you in your own private podcast feed.`) with underlined privacy phrase
- 3-step timeline explainer (numbered circles + connecting hairline) replaces the old ordered list
- Custom domain wired up: `https://feed-me.xyz` (with `www` cert too); old fly subdomain still works
- New test regression guards for `"private"` and `"Create your feed"` on the landing
- Step-desc grey bumped to `#6a6a6a` for WCAG AA contrast
- Spec: `docs/superpowers/specs/2026-05-25-landing-page-redesign.html`

## v1.0 — 2026-05-25

Initial release. End-to-end self-serve podcast feed:

- Self-serve onboarding at `/` → `POST /create` → `/u/<secret>` settings page
- iOS Shortcut → `GET /u/<secret>/ingest?url=...` spawns daemon worker
- Readability extracts article body → OpenAI TTS (`tts-1`, configurable voice) → MP3 written to `/data/<secret>/<slug>.mp3`
- RSS 2.0 feed at `/u/<secret>/feed.xml`; MP3s served from `/u/<secret>/audio/<slug>.mp3`
- Voice picker (shimmer / alloy / nova / echo) and URL rotation on settings page
- Failure visibility: failed ingests appear inline on the settings page with the error
- Deployed to Fly.io (sjc) on a 3GB volume; ~$2-5/mo + OpenAI TTS usage

End-to-end smoke verified: share `paulgraham.com/winc.html` → episode in Apple Podcasts ~60s later.
