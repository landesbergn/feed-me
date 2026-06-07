# Feed Me · API for agents

Feed Me turns articles into narrated podcast episodes in a private feed.
A user shares an article; a few minutes later it is in their podcast app,
read aloud. This page is for AI agents and scripts adding articles on a
user's behalf. Base URL: {base}

## TL;DR

You have a feed URL of the form {base}/u/<secret>. To narrate an article:

1. POST the article URL to {base}/u/<secret>/episodes.
2. Poll the returned status_url every few seconds until status is "ready".
3. Tell the user it is in their feed. Done.

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
      "remaining": 4
    }

Notes:

- "title" is null when the quick title fetch failed; the episode still
  processes normally.
- "remaining" is how many agent shares are left in the rolling 24-hour
  window (see Rate limit).
- Only http/https article URLs are accepted. Unknown body fields are
  ignored.

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
error, article too long). Narration usually takes one to a few minutes;
poll no faster than every few seconds. When an episode fails, report the
error to the user and do not retry the same URL.

## List the feed

    GET {base}/u/<secret>/episodes

    {
      "feed_page": "{base}/u/<secret>",
      "feed_url": "{base}/u/<secret>/feed.xml",
      "voice": "shimmer",
      "remaining": 3,
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

The 20 most recent episodes, newest first, plus the feed's voice and your
"remaining" agent quota. "audio_url" appears only on "ready" episodes;
"error" appears only on "failed" ones. Use this to confirm you have the
right feed (a 404 means the URL is wrong or was rotated, so ask the user)
and to check your remaining quota before sharing.

## Read the feed

    GET {base}/u/<secret>/feed.xml

The podcast RSS feed: every episode with titles, descriptions, and audio
URLs.

## Errors

| Status | error | Meaning | Retry? |
|--------|-------|---------|--------|
| 400 | invalid_request | Body is not JSON, or has no string "url" field | No: fix the request |
| 400 | invalid_url | URL is not http/https with a host | No: fix the URL |
| 404 | not_found | No feed at that secret, or no such episode | No: check the feed URL with the user |
| 429 | rate_limited | Agent cap reached | Not before Retry-After; tell the user |

Error bodies are JSON: {"error": "<code>", "message": "<human-readable>"}.

## Rate limit

5 episodes per feed per rolling 24 hours through this API. The user's own
phone sharing does not count against it. A 429 response includes a
Retry-After header (seconds). Do not retry before it elapses; tell the
user instead.

## Etiquette

- Save the feed URL the first time you get it; do not ask again next time.
- If you do not have the feed URL, ask the user. Never guess, scan history,
  or probe feeds.
- Share only what the user asked you to share.
- Do not retry permanent errors (400, 404).
- On 429, stop and tell the user.
- Poll the status URL no faster than every few seconds.
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
    created.raise_for_status()
    episode = created.json()

    status = episode
    while status["status"] == "pending":
        time.sleep(5)
        polled = httpx.get(episode["status_url"])
        polled.raise_for_status()
        status = polled.json()

    print(status["status"], status.get("audio_url") or status.get("error"))
