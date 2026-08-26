# Feed Me · API for agents

Feed Me turns articles into narrated podcast episodes in a private feed.
A user shares an article; a few minutes later it is in their podcast app,
read aloud. This page is for AI agents and scripts adding articles on a
user's behalf. Base URL: {base}

## TL;DR

You have a feed URL of the form {base}/u/<secret>. To narrate an article:

1. POST the article URL to {base}/u/<secret>/episodes.
2. Poll the returned status_url every 5 seconds until status is "ready"
   (usually one to two minutes; give up after ~10 minutes, see Poll status).
3. Tell the user it is in their feed. Done.

Undo a share with DELETE {base}/u/<secret>/episodes/<slug>.

    curl -s -X POST {base}/u/<secret>/episodes \
      -H 'Content-Type: application/json' \
      -d '{"url": "https://example.com/some-article"}'

## Step 0 · Remember this feed

The feed URL is the only credential and the only thing you need to do this
again. The first time a user gives it to you, save the feed URL to your
durable memory or project config so future requests need no URL and no
questions. For example, a Claude Code agent saves it to CLAUDE.md or its
memory directory; other agents save it wherever they keep per-user config.
The prompt the user pasted already contains the URL, so capture it once.

If you do not have the feed URL, ask the user for it. Never guess it, scan
history or past transcripts, or probe candidate feeds. A guessed feed is
the wrong feed.

## Auth: the feed URL is the credential

There is no API key and no signup. The user gives you their feed page URL:

    {base}/u/<secret>

The secret in that URL is their entire account. Treat it like a password:

- Never log it, post it publicly, or echo it into shared context.
- If you do not have it, ask the user. Never guess or rediscover it.
- If you believe it leaked, tell the user to use "Rotate URL" on their
  feed page (the old URL stops working).

## Add an article

    POST {base}/u/<secret>/episodes
    Content-Type: application/json

    {"url": "https://example.com/some-article"}

Response: 202 Accepted

    {
      "slug": "k3kQ9rTzVx0",
      "status": "pending",
      "title": "The Article Title",
      "status_url": "{base}/u/<secret>/episodes/k3kQ9rTzVx0",
      "feed_page": "{base}/u/<secret>",
      "remaining": 4,
      "budget_remaining_chars": 287500
    }

Notes:

- "title" is null when the quick title fetch failed; the episode still
  processes normally.
- "remaining" is how many agent shares are left in the rolling 24-hour
  window (see Rate limit).
- "budget_remaining_chars" is how many characters of narration the feed can
  still request in that window (see Rate limit). Check it before sending long
  text so you do not get a 429.
- Only http/https article URLs are accepted. Unknown body fields are
  ignored.

## Narrate text directly

If you already hold the full text of an article or email (for example a
newsletter the user receives in full as a paying subscriber), send the text
itself instead of a URL. Feed Me narrates it as-is and never fetches anything,
so it is not subject to the paywall a server-side fetch would hit.

    POST {base}/u/<secret>/episodes
    Content-Type: application/json

    {
      "text": "The full article or email body to narrate...",
      "title": "The Episode Title",
      "url": "https://example.com/the-source"
    }

- "text" is the body to narrate (plain text; strip HTML first).
- "title" is required (there is no page to derive one from).
- "url" is optional: it becomes the episode's "Original article" link and is
  never fetched. Omit it when there is no canonical source.

The response is the same 202 shape as a URL share, and the same rate limit
and narration budget apply. Over-long text (more than the per-episode limit of
100,000 characters) and empty text are rejected immediately. Prefer text over a
URL whenever you have the full body and the URL would be paywalled.

## Poll status

    GET {base}/u/<secret>/episodes/<slug>

    {
      "slug": "k3kQ9rTzVx0",
      "status": "pending",
      "title": "The Article Title",
      "ts": 1781234567,
      "total_chunks": 12,
      "error": null
    }

"status" moves from "pending" to "ready" (an "audio_url" field appears) or
"failed" ("error" holds a human-readable reason: paywalled article, fetch
error, article too long). "ts" is the last-update unix time, not a fixed
created-at, so do not use it to measure elapsed time; track your own start
time instead.

Timing and when to give up:

- Narration is usually ready in one to two minutes; a long article takes a
  bit more. Poll no faster than every five seconds.
- The server bounds each step, so a healthy episode does not sit pending for
  long. If "status" is still "pending" after about 10 minutes, treat it as
  stuck: stop polling, tell the user, and optionally delete it (see below)
  and try once more. Do not poll indefinitely.
- When an episode fails, report the error to the user and do not retry the
  same URL.

## List the feed

    GET {base}/u/<secret>/episodes

    {
      "feed_page": "{base}/u/<secret>",
      "feed_url": "{base}/u/<secret>/feed.xml",
      "voice": "shimmer",
      "remaining": 3,
      "budget_remaining_chars": 245000,
      "episodes": [
        {
          "slug": "k3kQ9rTzVx0",
          "title": "The Article Title",
          "status": "ready",
          "ts": 1781234567,
          "audio_url": "{base}/u/<secret>/audio/k3kQ9rTzVx0.mp3"
        }
      ]
    }

The 20 most recent episodes, newest first, plus the feed's voice and both of
your remaining limits: "remaining" (episode count) and "budget_remaining_chars"
(narration characters). "audio_url" appears only on "ready" episodes; "error"
appears only on "failed" ones. Use this to confirm you have the right feed (a
404 means the URL is wrong or was rotated, so ask the user) and to check both
limits before sharing.

## Remove an episode

    DELETE {base}/u/<secret>/episodes/<slug>

    {"slug": "k3kQ9rTzVx0", "status": "deleted"}

Undo a share you created: a wrong link, a duplicate, or a stuck episode you
are about to retry. It removes the episode from the feed immediately (the RSS
rebuilds on the next fetch). A 404 means there is no such episode (already
gone, or wrong slug). Works on an episode in any state: pending, ready, or
failed. Delete only episodes you added; do not clean up the user's feed
unless they ask.

## Read the feed

    GET {base}/u/<secret>/feed.xml

The podcast RSS feed: every episode with titles, descriptions, and audio
URLs.

## In a browser (WebMCP)

If you are browsing with WebMCP support (ChatGPT's browser, or Chrome with
WebMCP enabled), you do not need this API by hand. Open the user's feed page
{base}/u/<secret> and the page registers tools: add_article,
add_article_text, list_episodes, get_episode_status, delete_episode,
set_voice, get_feed_info, and help_subscribe. A user with no feed yet can
start at {base}/ where a create_feed tool registers. After creating a
feed, call help_subscribe: getting the feed into the user's podcast app is
the one setup step that matters. The HTTP API on this page is the same
capability set and works everywhere else.

Example prompts a user might give you, one per tool:

- create_feed (on the landing page): "Set me up a Feed Me podcast feed."
- help_subscribe: "Help me get this feed into my podcast app."
- add_article: "Send this article to my feed."
- add_article_text: "Narrate your summary of this thread into my feed."
- list_episodes: "What's in my listening queue?"
- get_episode_status: "Is my episode ready yet?"
- delete_episode: "Remove that last episode."
- set_voice: "Switch my feed's voice to nova."
- get_feed_info: "What's my feed's RSS link so I can subscribe?"

## Errors

| Status | error | Meaning | Retry? |
|--------|-------|---------|--------|
| 400 | invalid_request | Body is not JSON, or is missing a valid "url" (or "text" with a "title") | No: fix the request |
| 400 | invalid_url | URL is not http/https with a host | No: fix the URL |
| 404 | not_found | No feed at that secret, or no such episode | No: check the feed URL with the user |
| 403 | suspended | This feed is suspended from new narration | No: tell the user to contact the feed owner |
| 429 | rate_limited | Agent cap reached (episode count) | Not before Retry-After; tell the user |
| 429 | budget_exceeded | Feed narration character budget reached | Not before Retry-After; tell the user |

Error bodies are JSON: {"error": "<code>", "message": "<human-readable>"}.

## Rate limit

Two limits apply per feed over a rolling 24-hour window, and the user's own
phone sharing counts against neither:

1. Episode count: 5 episodes per feed. "remaining" reports what is left.
2. Narration budget: a character total across all episodes (roughly the TTS
   cost). "budget_remaining_chars" reports what is left, and each episode is
   itself capped at 100,000 characters.

Both return 429 with a Retry-After header (seconds); budget_exceeded means the
feed hit the character total, not the episode count. Splitting text into smaller
pieces does not raise the budget (it is a per-feed total). Do not retry before
Retry-After elapses; tell the user instead.

## Etiquette

- Save the feed URL the first time you get it; do not ask again next time.
- If you do not have the feed URL, ask the user. Never guess, scan history,
  or probe feeds.
- Share only what the user asked you to share.
- Do not retry permanent errors (400, 404).
- On 429, stop and tell the user.
- Poll the status URL no faster than every five seconds, and stop after about
  10 minutes: a still-pending episode by then is stuck, not slow.
- To undo a share you created (wrong link, duplicate), DELETE it. Do not
  delete episodes you did not add unless the user asks.
- Send a descriptive User-Agent so your traffic is identifiable.

## Example: curl

    curl -s -X POST {base}/u/<secret>/episodes \
      -H 'Content-Type: application/json' \
      -d '{"url": "https://example.com/some-article"}'

## Example: Python

    import time
    import httpx

    feed = "{base}/u/<secret>"      # the URL the user gave you
    # Save `feed` to your durable memory so you need not ask again next time.

    created = httpx.post(
        feed + "/episodes",
        json={"url": "https://example.com/some-article"},
    )
    # A 429 here is rate_limited (5-episode cap) or budget_exceeded (character
    # budget). Both are per-feed and per rolling 24h: do not retry before the
    # Retry-After header elapses, and do not split the text to route around the
    # budget (it is a per-feed total). Stop and tell the user instead.
    created.raise_for_status()
    episode = created.json()

    # Poll, but never forever: give up after ~10 minutes and treat as stuck.
    deadline = time.monotonic() + 600
    status = episode
    while status["status"] == "pending" and time.monotonic() < deadline:
        time.sleep(5)
        polled = httpx.get(episode["status_url"])
        polled.raise_for_status()
        status = polled.json()

    if status["status"] == "ready":
        print("ready:", status["audio_url"])
    elif status["status"] == "failed":
        print("failed:", status["error"])      # report to user; do not retry
    else:
        print("stuck: still pending after 10 min; telling the user")
        # Optional: undo and try once more.
        # httpx.delete(feed + "/episodes/" + episode["slug"])
