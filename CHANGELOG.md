# Changelog

## v3.21 · 2026-08-18

Keep the Full Text Shortcut generic: identify by cookie, not by a pasted secret.

- New `GET /share/text` + `POST /share/text`. The Shortcut opens `https://feed-me.xyz/share/text#t=<article text>&title=...&u=...` in Safari, which carries `fm_session` exactly as `/share` does, so one Shortcut works for everyone and carries no secret and no install question. The page's JS reads the fragment and posts it back as a form; browsers never send a fragment, so the article text stays out of the request logs.
- Both text entry points now share `_create_text_episode()` (validation, title fallback, the 30/day cap, the per-feed character budget, `MAX_BODY_CHARS`), raising `TextShareError` that the API route renders as `{"error", "message"}` and the page renders as the same "Couldn't add that" screen `/share` uses. Success renders `share.html`'s "added" state, so the progress bar and status polling are unchanged.
- No fragment (a very long article whose URL didn't survive iOS) falls back to a paste box on the same page instead of failing.
- `_ga.html` gained `ga_path_override`, and `/share/text` sets it: gtag reports `location.href` verbatim, and this page's fragment holds article text, so the reported location is the bare path. Same rule as the `/u/<secret>` mask, different reason.
- The fragment is parsed by hand rather than with `URLSearchParams`, which decodes `+` as a space and would corrupt any article containing one.

## v3.20 · 2026-08-18

Narrate paywalled articles by extracting them on the phone.

- New `POST /u/<secret>/share-text`: takes article text the iOS Shortcut extracted from the page Safari already rendered (subscriber session included) and narrates it without ever fetching the URL. Path-secret auth like the agent API, no session cookie, `{"error", "message"}` errors, and it accepts a form body as well as JSON because Shortcuts' Get Contents of URL posts a form by default. Episodes record `via: "shortcut"`.
- This is the only path that works for sites that refuse server fetches outright. Verified 2026-08-18: nytimes.com article pages 403 every non-browser client (Safari UA with full `Sec-Fetch-*` headers, Chrome UA, Googlebot UA, forced HTTP/2), gift links included, while the homepage and `/athletic/` index return 200. Sharing from the NYT *app* still cannot work: iOS hands over only a URL and a headline, and the body never leaves the app.
- Its own `SHORTCUT_DAILY_CAP` (30/rolling 24h) via the generalized `_episodes_in_window(secret, via, now)`: the agent cap of 5/day is a guard on automation and would cut a person off mid-morning, and neither entry point spends the other's allowance. Both still share the per-feed `AGENT_FEED_CHAR_BUDGET`, which is the actual cost guard, and `MAX_BODY_CHARS` still bounds one episode.
- An empty title falls back to the first line of the extracted text (Get Details of Article can return an empty name), then the source hostname, so a share never fails on a missing title.
- New `SHORTCUT_TEXT_ICLOUD_URL` env var and an optional "Paywalled sites" row on the settings page that installs the second Shortcut. Unset (the default) hides the row entirely.

## v3.19 · 2026-08-18

Survive share sheets that hand over text instead of a link.

- New `app.extract_shared_url()`: `/share` now pulls the first `http(s)` URL out of whatever the Shortcut passes, so a share like `Headline https://example.com/a` ingests the article instead of failing. Bare URLs behave exactly as before.
- When the shared text contains no link at all (the NYT / Athletic app can hand over the article dek, which is what a tester hit), the failure now says so and points at the fix ("Open the article in Safari and share from there, or use the app's Copy Link"), instead of the opaque `Invalid URL: '<the whole dek>'`. A wrong-scheme share (`ftp://…`) still reads as `Invalid URL`, and an empty share still reads as "No article added".
- The failed-episode row stores at most 120 characters of the shared text, so a stray paragraph no longer becomes a giant title in the feed.
- Paywall failures now name the workaround: the declared-paywall preview error (`ingest.fetch_article`) ends with "If the app offers a gift link, share that instead: it opens for anyone, so Feed Me can read it too." A gift link renders in full to an anonymous fetch, and the audio outlives the link's expiry, so it is the one thing a subscriber can do that works when the site actually served us a teaser.
- The 401/402/403 error (`_friendly_http_error`) says the opposite, because a 403 is a bot block that fires *before* any unlock logic: "The site refuses readers that aren't a browser, or the article needs a subscription. Nothing you share will get past this one: on nytimes.com even a gift link is refused, so don't spend one." Verified 2026-08-18: nytimes.com article pages 403 a plain client under a Safari UA with full `Sec-Fetch-*` headers, a Chrome UA, a Googlebot UA, and forced HTTP/2, while the homepage and `/athletic/` index return 200, and a real gift link failed the same way in production. Other HTTP failures (404, 5xx) are unchanged.
- The companion client-side fix (not in this repo): the "Feed Me" Shortcut should run **Get URLs from Input** on Shortcut Input before URL Encode, so iOS hands over the URL attachment when an app offers both text and a link.

## v3.18 · 2026-07-11

Hard-block a feed from generating new audio.

- New `BLOCKED_FEED_HASHES` set in `app.py`: any feed whose `analytics.feed_hash(secret)` is listed is refused all new TTS. The match is on the one-way feed hash (the same 12-char id shown on `/admin/stats`), so the raw secret never appears in source or logs, and a hash can be pasted straight from the stats page. Seeded with `dd8d9ed021f8`, whose agent pipeline was driving OpenAI cost past what the per-feed budget (v3.17) alone would bound.
- `POST /u/<secret>/episodes` returns `403 suspended` (`{"error": "suspended", "message": ...}`) for a blocked feed, before parsing the body or spawning any work, so no OpenAI call is made. The message names the reason and points to a contact, per the "clear error so they understand why" call. The `/share` shortcut path shows a matching "Feed suspended" page (defense in depth: the block covers every TTS entry point). Read paths (`GET`/`DELETE` episodes, the feed, RSS, existing audio) stay open, so a block reads as a suspension, not a rotated or deleted secret.
- Reversible: remove the hash and redeploy. New `app._is_blocked()` helper; new tests cover the agent-API 403 (with an empty fake-OpenAI call log proving no spend), the still-open read path, and the suspended share page.

## v3.17 · 2026-07-09

Cap agent narration cost: lower the per-episode limit and add a per-feed budget.

- `ingest.MAX_BODY_CHARS` drops from 500,000 to 100,000 (about 50 minutes of `tts-1` audio, ~$1.50 max per episode). Articles longer than that are rejected, same as before, just at a lower threshold. This re-narrows the window widened in v3.14; the tradeoff is that a single very long document (the ~265k-char "encyclical" case) must now be split.
- New per-feed narration budget on the agent API: `AGENT_FEED_CHAR_BUDGET` (300,000 characters per feed per rolling 24h, ~$4.50/day/feed) alongside the existing 5-episode count cap. Characters map directly to TTS cost, so this bounds spend regardless of how an agent splits its pushes. Over-budget requests get a `429 budget_exceeded` with a `Retry-After` and a message that explains the cap is a per-feed total and that splitting or retrying will not raise it (so an agent throttles instead of trying to route around it). Text mode is metered exactly at request time; URL mode (unknown length until fetch) is blocked only once the feed is already at budget.
- Episodes now record a `chars` count (`storage.write_*_episode`), which is what the budget meters. Failed text-mode episodes still count so a failing-and-retrying agent cannot narrate for free; failed URL fetches (no confirmed length) do not.
- Both `POST` and `GET /u/<secret>/episodes` now return `budget_remaining_chars` so an agent can self-regulate. `AGENTS.md` documents the budget, the new error code, and the 100k per-episode limit.

## v3.16 · 2026-06-08

Let an agent undo a share, and tell agents when to stop polling.

- New `DELETE /u/<secret>/episodes/<slug>` on the agent API: undo a share (wrong link, duplicate, a stuck episode you are about to retry). Path-secret auth, JSON only, no cookies, same `{"error", "message"}` shape as the rest of the agent API; returns `{"slug", "status": "deleted"}` on success and 404 for an unknown slug. Removes the episode's `.json` (which drops it from the feed/RSS, both of which rebuild per request) and best-effort its `.mp3`. New `storage.delete_episode()` helper. Closes the create -> poll -> delete lifecycle so neither the agent nor the operator has to hand-edit the volume to remove an episode.
- `AGENTS.md` now tells agents *when to give up*: poll no faster than every 5s and stop after ~10 min, because a still-pending episode by then is stuck, not slow (the old guidance and the Python example polled `while pending` with no bound, which is exactly how a transient stall reads as a 25-minute hang). Documents the new delete endpoint, clarifies that `ts` is a last-update time (not a fixed created-at, so agents should track their own start time), and the Python example now uses a bounded poll loop with explicit ready / failed / stuck branches.

## v3.15 · 2026-06-08

Bound a stalled TTS call so an episode can't hang for 10+ minutes.

- The OpenAI client now sets `timeout=httpx.Timeout(60.0, connect=5.0)` instead of riding the SDK default (600s read). The default `read` is a *silence* timeout (it only fires after 600s with no bytes received), so a slow-trickling or stalled `tts-1` call could block for ~10 min per attempt. `synthesize()` writes chunks in input order via `pool.map`, so the whole job is gated on the slowest chunk; one stalled chunk held a real 12-chunk article (newyorker.com, ~48k chars) at "pending" for ~21 min, with `max_retries=5` masking the stall instead of recovering fast.
- `read=60s` caps a stalled call so a retry fires within ~1 min; `connect` stays at the SDK default 5s. tts-1 latency for a 4000-char chunk is seconds, so 60s leaves wide headroom over legitimate generation, and the existing retries re-attempt the now-bounded call. Concurrency (`TTS_MAX_PARALLEL = 12`) is unchanged: it is what keeps long articles at ~90s, and lowering it would not rescue a stalled call (the order-preserving `pool.map` blocks on the slowest chunk regardless of batch size).

## v3.14 · 2026-06-07

Narrate supplied text.

- `POST /u/<secret>/episodes` now accepts `{"text": "...", "title": "..."}` to narrate an article or email body directly, with no server-side fetch. This bypasses paywalls when the user already receives the full text (for example a newsletter they get as a paying subscriber); a browser fetch of the URL would see only the preview. An optional `url` becomes the episode's source link.
- `title` is required in text mode; over-length text (more than 500,000 characters) and empty text are rejected at request time, so they never create an episode or spend a rate-limit share.
- A text episode with no source link omits the "Original article" line in the feed instead of showing a broken link.

## v3.13 · 2026-06-07

Seamless agent sharing.

- New `GET /u/<secret>/episodes`: a JSON listing of the feed (the 20 most recent episodes, newest first) plus the feed's voice and the agent's remaining 24h quota. Path-secret auth, no cookie, the same `{"error","message"}` errors as the other agent endpoints; a 404 doubles as the cheap "is this feed real?" check. Previously this path accepted only POST and returned 405 to a GET.
- `AGENTS.md` rewritten to lead with the happy path, tell agents to save the feed URL on first contact ("Step 0 · Remember this feed"), and never guess, scan history, or probe feeds when they lack the URL. The list endpoint is documented.
- The "For your agent" prompt now tells the agent to save the feed page so it does not have to ask again.

## v3.12 — 2026-06-07

Landing page robot: drop the speech bubble 18px so its tail meets the robot's face instead of floating above its head.

## v3.11 — 2026-06-07

The "For your agent" tab now shows the agent prompt inline (click-to-copy) plus the `AGENTS.md` link, instead of linking to a separate page. The standalone `/u/<secret>/agents` page is removed.

## v3.10 — 2026-06-07

For Agents UI polish.

- The "Share an article" section gains a "For you / For your agent" tab toggle. "For you" (default) shows the iOS share-sheet steps; "For your agent" shows the "Your agent can share here too" card linking to the agents page. The standalone agent card under the episodes is gone.
- Landing page robot bubble now reads "or have your agent send things" and is decoration only (no longer links to `AGENTS.md`).

## v3.9 — 2026-06-06

For Agents UI: the agent prompt gets a proper home.

- New page `/u/<secret>/agents`: the copy-paste agent prompt (click the box to copy) plus a link to `AGENTS.md`. Reached from an always-visible card under the episodes: "Your agent can share here too".
- The collapsed "For agents" fold (v3.6) is gone from the feed page.
- Landing page: a small robot peeks over the "Share any article" step saying "or have your AI agent send things", linking to `AGENTS.md`.
- Prompt copy trimmed: the daily-cap detail lives only in `AGENTS.md`; the privacy line and "(Claude Code and friends)" are removed.

## v3.8 — 2026-06-06

Article cap raised 100k → 500k chars (~4h10m audio, ~$7.50 max cost):

- `MAX_BODY_CHARS` 100_000 → 500_000. Triggered by a 265k-char encyclical share failing with "Article too long". One article stays one episode (multi-part splitting considered and rejected).
- `synthesize()` bounds its pool at `TTS_MAX_PARALLEL = 12` workers (was unbounded; the old justification "worst-case 25 chunks stays under 50 req/min" died with the old cap, since 500k chars is up to 125 chunks). Articles of 12 chunks or fewer (~48k chars, the typical case) are unaffected.
- The worker bound can't bound requests/min (that depends on per-call latency), so the client is constructed with `max_retries=5`: the SDK's 429 backoff honoring Retry-After is the actual rate-limit guarantee.
- The first production run (265k chars, 69 chunks) OOM-killed the 1GB VM (`anon-rss: 866MB`): `pool.map` futures held ~300MB of MP3 and `b"".join` doubled it; at the 500k cap the buffers alone would be ~1.1GB. `synthesize()` now streams to disk: sequential batches of `TTS_MAX_PARALLEL` chunks append to `<slug>.mp3.tmp` and `write_episode(audio_path=...)` atomic-renames it into place. Peak audio memory is one batch (~50MB) at any article length; a mid-stream crash leaves a cleaned-up `.tmp`, never a ready episode with partial audio. Concurrent ingests remain uncapped (~50MB each now).
- Spec: `docs/superpowers/specs/2026-06-06-article-cap-500k.html`

## v3.7 — 2026-06-05

Audience analytics via Google Analytics 4.

- The landing, settings, and share pages load GA4 (`G-MQ15LHLSBF`) through a
  shared `templates/_ga.html` partial: device, browser, city/state/country, and
  referrer reporting. The admin page is not tracked.
- The feed secret never reaches Google: the settings page reports its location
  as `/u/_`, and any `/u/<secret>` referrer is masked before the config fires.
- The self-hosted SQLite analytics and `/admin/stats` are unchanged.

## v3.6 — 2026-06-05

For agents: AI agents can add articles to a feed.

- New agent API: `POST /u/<secret>/episodes` (JSON in, 202 + status URL out) and `GET /u/<secret>/episodes/<slug>` for polling. Authenticated by the path secret only; the session cookie is never read or set on these routes.
- `/AGENTS.md` (plus an `/llms.txt` pointer) documents the API for agents: endpoints, stable error codes, etiquette, rate limit, curl/Python examples.
- "For agents" section on the feed page with a copy-paste prompt personalized to the feed.
- Agent shares capped at 5 per feed per rolling 24h (429 + `Retry-After` beyond that); phone sharing is never throttled. The `via: "agent"` record tag now survives episode finalization so the cap counts completed episodes, not just pending ones.
- `article_shared` analytics carry `via: "agent" | "shortcut"`. No user-agent strings are stored (keeps the v3.1 analytics privacy promise).

## v3.5 — 2026-06-05

Stats: Pacific time + totals rows.

- All `/admin/stats` timestamps now render in Pacific time (DST-aware via `zoneinfo`) instead of UTC: "Recently shared" times and the by-day activity buckets. The by-day grouping happens in Python (SQLite can't group by a named timezone), so a 10 PM PT share no longer lands on the next day's row.
- "All feeds" and "Activity by day" tables gain a bold totals row (feed count + summed shares / page views / feeds created).
- `tzdata` added as an explicit dependency: the slim prod container has no system zoneinfo, and the package previously arrived only transitively via trafilatura's chain. A regression test resolves the zone with the system tz path emptied, simulating the container.

## v3.4 — 2026-06-03

Fixes from early-user reports (truncated narration, paywall 403s, empty shares):

- **Full-article extraction.** `fetch_article` now runs trafilatura alongside readability and keeps whichever body is longer. Fixes newyorker.com narration stopping mid-article at ~4:30: readability silently extracted only the first half (4,347 of 7,905 chars); same symptom as the pre-v1.7 truncation but rooted in extraction, not synthesis. Title still comes from the readability path and is stripped from the winning body. New dependency: `trafilatura`.
- **Browser Accept headers on fetches.** nytimes.com 403s requests missing the `Accept` / `Accept-Language` headers a real browser sends (the spoofed UA alone changes nothing; verified by isolating headers vs UA). Note: NYT still serves only a teaser without subscriber cookies, and Fly's datacenter IPs may be blocked harder than local testing; verify after deploy.
- **Friendly fetch errors.** HTTP failures surface human copy ("nytimes.com blocked the request (HTTP 403). The article may need a subscription.") instead of httpx's raw exception string, which leaked onto the share page truncated mid-URL ("For more information check: https://developer.mozilla.").
- **Teaser guard.** Bodies under 600 chars now fail with "may be paywalled" copy instead of becoming a silent 20-second episode that looks complete.
- **Paywall detection (no site list).** Pages that declare themselves paywalled in their own markup (schema.org `isAccessibleForFree: false`, Facebook `article:content_tier: locked`) and serve under 2,500 chars of extractable text fail fast with "subscriber-only" copy. Declared-paywalled pages that serve the full text anyway (metered sites) still narrate, so this catches the NYT teaser without breaking sites like newyorker.com.
- **Empty-share copy.** `/share` with no URL (a tester ran the Shortcut directly from the Shortcuts app) now says "No article added. Open an article, tap Share, then tap Feed Me." instead of the diagnostic "Shortcut sent no article URL."

## v3.3 — 2026-06-02

Stats: full feeds table.

- `/admin/stats` gains an "All feeds" table listing every feed on disk: hashed id, date created (from `settings.json`), last accessed (the newest tracked event for that feed), and total shares. Sorted by last accessed, newest first; feeds with no tracked activity show "never".
- Removed the now-redundant "Top feeds (by shares)" table; its per-feed share counts live in the All feeds table's Shares column. (`/admin/export` still carries `top_feeds` in its summary.)
- "Recently shared" columns reordered to feed, then when, then article (still the most recent 25).
- Privacy unchanged: the table reads the filesystem but renders only the one-way `sha256(secret)[:12]` hash; the raw secret is hashed in the route and never reaches the page, export, or logs.
- New helpers: `storage.list_feeds`, `analytics.feed_last_accessed`, `analytics.feed_share_counts`.
- Spec: `docs/superpowers/specs/2026-06-02-stats-feeds-shares-tables.html`

## v3.2 — 2026-06-02

Analytics: capture what's shared.

- `article_shared` events now record the article URL + title (in the event's `props`), so analytics can answer "what's been shared," not just how many.
- `/admin/stats` gains a "Recently shared" table (newest first: time, hashed feed, article title linked to its URL); `/admin/export` carries url/title on each event.
- Privacy note: the analytics DB now stores article URLs/titles keyed by the one-way hashed feed id (still no raw secret). Older shares from before this change show as "(unknown)".

## v3.1 — 2026-06-02

Basic analytics:

- Self-hosted SQLite event store (`analytics.py`, stdlib only — no new dependency, no third party) on the Fly volume at `_analytics/analytics.db` (its own subdir so the `/data/<secret>/` feed level stays pure).
- Tracks `page_view`, `feed_created`, and `article_shared`, each attributed by a one-way `sha256(secret)[:12]` hash — the raw feed secret is never stored, so analytics can't reveal a private feed URL.
- Token-gated `/admin/stats` (HTML summary) and `/admin/export` (JSON of summary + raw events, for later analysis); both 404 without the correct `STATS_TOKEN`. Analytics failures can never break a page (fire-and-forget, swallowed).
- Spec: `docs/superpowers/specs/2026-06-02-analytics.html`

## v3.0 — 2026-06-01

Frictionless share capture:

- Replaced the per-user copy/paste Shortcut install with **one generic Shortcut** for everyone — installs in one tap, no secret to paste. Sharing an article opens `/share?url=…` in Safari and shows an instant "🎧 Added to your feed" confirmation.
- New `GET /share` route identifies the user by a long-lived first-party `fm_session` cookie (set whenever you view your feed page), so rotating your secret no longer breaks capture — re-link by reopening your feed page.
- Removed the per-user `/u/{secret}/ingest` route and the entire clipboard/paste install flow (no backward compat — no existing users).
- Failed episode rows now show the **real error** (e.g. an OpenAI quota message) instead of the misleading "(couldn't extract article)" label.
- Episode show notes now link to the **original article** and carry a "Generated with Feed Me" link back to your feed page; the podcast's description includes a "Your feed:" return link.
- Spec: `docs/superpowers/specs/2026-05-29-frictionless-share-capture.html`

## v2.0 — 2026-05-29

Pending progress indicator:

- Pending rows now show a smooth percent (e.g., "Pending · 42%") that ticks up every second so friends can see ingest is alive.
- Percent is computed client-side from elapsed time and `total_chunks` (written to the pending record after `chunk_text` runs). Caps at 95% until the row actually flips to Ready, never goes backwards.
- New `storage.update_pending_episode(slug, *, total_chunks=N)` helper updates an existing pending record without losing other fields.
- Spec: `docs/superpowers/specs/2026-05-29-pending-progress-indicator.html`

## v1.9 — 2026-05-28

Share-sheet onboarding:

- Share section now correctly explains the iOS share-sheet flow: tap Share → tap **More ▼** → scroll to bottom → tap Feed Me. Previous instructions skipped the "More" step entirely, which meant friends following the page couldn't find Feed Me at all.
- New "💡 Pin Feed Me for one-tap sharing" tip callout: 4-step instructions for moving Feed Me to the top of the share sheet via Edit Actions / Edit Suggestions. Future shares become one tap.
- Small inline CSS-rendered illustration of the share sheet showing where More ▼ sits.
- Spec: `docs/superpowers/specs/2026-05-28-share-sheet-onboarding.html`

## v1.8 — 2026-05-28

Parallel TTS — 10 min → ~90s for long articles:

- `synthesize()` now issues all chunked TTS calls in parallel via `ThreadPoolExecutor` instead of a sequential `for` loop. `pool.map()` preserves input order so MP3 bytes are still concatenated chronologically.
- No bounded concurrency: worst-case 25 chunks (100k char cap) stays under OpenAI's 50 req/min tier-1 rate limit.
- New regression test guards against switching back to completion-order output.
- Spec: `docs/superpowers/specs/2026-05-27-parallel-tts.html`

## v1.7 — 2026-05-27

Fixes silent audio truncation on long articles:

- `synthesize()` now chunks the article body at sentence boundaries and makes multiple TTS calls instead of truncating to the first 4000 chars. MP3 bytes are concatenated naively (works because tts-1 frames are self-contained). Articles over 4 min (~600 words) now play through to the end.
- Hard cap at 100k chars per article (~50 min of audio, ~$1.50 max cost). Articles over the cap fail with the message "Article too long: NNN,NNN chars (limit: 100,000)..." visible on the settings page, instead of silently running up cost.
- Spec: `docs/superpowers/specs/2026-05-27-tts-chunking-and-length-cap.html`

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
