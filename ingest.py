import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import httpx
import trafilatura
from readability import Document
from lxml import html as lxml_html
from openai import OpenAI

import storage

log = logging.getLogger("ingest")

http_client = httpx.Client(
    timeout=30.0,
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        ),
        # Some sites (verified: nytimes.com) 403 any request missing the
        # Accept / Accept-Language headers a real browser always sends; the
        # spoofed UA alone is not enough.
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    },
    follow_redirects=True,
)

# max_retries=5 (SDK default 2): 429 retries are the rate-limit correctness
# guarantee for long articles (see synthesize), so give them headroom.
# timeout: the SDK default is 600s read, which is a *silence* timeout (it only
# fires after 600s with no bytes), so a slow-trickling or stalled TTS call can
# block for ~10 min per attempt. A single stalled chunk once held a 12-chunk
# article at "pending" for ~21 min (the ordered pool.map gates the whole job on
# the slowest chunk, and max_retries masked the stall instead of recovering
# fast). read=60s caps a stalled call so a retry fires within ~1 min; connect
# stays at the SDK default 5s. tts-1 latency for a 4000-char chunk is seconds,
# so 60s has wide headroom over legitimate generation.
openai_client = OpenAI(  # reads OPENAI_API_KEY from env
    max_retries=5,
    timeout=httpx.Timeout(60.0, connect=5.0),
)

TTS_CHAR_LIMIT = 4000
TTS_MODEL = "tts-1"
TTS_MAX_PARALLEL = 12  # synthesize() batch size and worker bound; see comment there
DESCRIPTION_EXCERPT_CHARS = 200
TITLE_FETCH_TIMEOUT_S = 5.0
MAX_BODY_CHARS = 500_000  # ~4h10m of TTS audio, ~$7.50 max cost per article
MIN_BODY_CHARS = 600  # below this it's a teaser/paywall shell, not an article
# On a page that declares itself paywalled, anything under this is a teaser
# (nytimes.com serves ~1,800 chars without subscriber cookies); above it the
# site evidently served the full text anyway, so narrate it.
PAYWALL_BODY_MIN_CHARS = 2500

# Machine-readable paywall declarations: schema.org's isAccessibleForFree
# (publishers must set it for Google to index gated content) and Facebook's
# article:content_tier. Read from the page's own markup; never a site list.
_PAYWALL_DECLARATIONS = (
    re.compile(r'"isAccessibleForFree"\s*:\s*"?[Ff]alse"?'),
    re.compile(r'article:content_tier["\'][^>]*content=["\']locked'),
    re.compile(r'content=["\']locked["\'][^>]*article:content_tier'),
)


def _declares_paywall(html_text: str) -> bool:
    return any(p.search(html_text) for p in _PAYWALL_DECLARATIONS)


class FetchError(RuntimeError):
    """An article URL couldn't be fetched. str() is user-facing copy (it lands
    on the share page and the failed episode row), so keep it friendly."""


def _friendly_http_error(status: int, url: str) -> str:
    host = urlparse(url).netloc or url
    if status in (401, 402, 403):
        return (
            f"{host} blocked the request (HTTP {status}). "
            "The article may need a subscription."
        )
    if status in (404, 410):
        return f"Article not found at {host} (HTTP {status}). The link may be broken."
    if status >= 500:
        return f"{host} had a server error (HTTP {status}). Try sharing again in a few minutes."
    return f"Couldn't fetch the article from {host} (HTTP {status})."


def _readability_extract(html_text: str) -> tuple[str, str]:
    """Title + raw body via readability (the original extraction path)."""
    doc = Document(html_text)
    summary_elem = lxml_html.fromstring(doc.summary())

    # Try to extract h1 as title, fall back to page title
    h1s = summary_elem.xpath('.//h1')
    if h1s:
        title = h1s[0].text_content().strip()
    else:
        title = doc.short_title() or doc.title()
    return title, summary_elem.text_content().strip()


def _trafilatura_extract(html_text: str) -> str | None:
    """Raw body via trafilatura, or None when it finds nothing (or blows up).

    Second opinion alongside readability: on some sites readability silently
    keeps only part of the article (verified on newyorker.com, where it
    returned the first half and the narration stopped mid-piece)."""
    try:
        return trafilatura.extract(html_text, include_comments=False)
    except Exception:
        return None


def _clean_body(body: str, title: str) -> str:
    """Strip a leading title (so it isn't narrated twice) and blank lines."""
    if title and body.startswith(title):
        body = body[len(title):].strip()
    return "\n\n".join(line.strip() for line in body.splitlines() if line.strip())


def fetch_article(url: str) -> tuple[str, str]:
    resp = http_client.get(url)
    if resp.status_code >= 400:
        raise FetchError(_friendly_http_error(resp.status_code, url))

    title, readability_body = _readability_extract(resp.text)
    candidates = [_clean_body(readability_body, title)]
    trafilatura_body = _trafilatura_extract(resp.text)
    if trafilatura_body:
        candidates.append(_clean_body(trafilatura_body.strip(), title))
    # Longest extraction wins: an extractor that missed part of the article
    # can't beat one that got all of it.
    body = max(candidates, key=len)

    if len(body) < PAYWALL_BODY_MIN_CHARS and _declares_paywall(resp.text):
        raise FetchError(
            f"{urlparse(url).netloc} marks this article as subscriber-only "
            f"and served only a preview ({len(body)} characters of text)."
        )
    return title, body


def fetch_title(url: str) -> str | None:
    """Quick HTTP GET to extract just the <title> tag. Returns None on any failure."""
    try:
        resp = http_client.get(url, timeout=TITLE_FETCH_TIMEOUT_S)
        resp.raise_for_status()
    except Exception:
        return None
    try:
        doc = lxml_html.fromstring(resp.text)
        title_el = doc.find(".//title")
        if title_el is not None and title_el.text:
            stripped = title_el.text.strip()
            return stripped or None
    except Exception:
        return None
    return None


def _excerpt(body: str, max_chars: int) -> str:
    """First `max_chars` of body, broken at a word boundary, with ellipsis if truncated."""
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars]
    last_space = cut.rfind(" ")
    if last_space > max_chars * 0.5:
        cut = cut[:last_space]
    return cut + "…"


def chunk_text(body: str, max_chars: int) -> list[str]:
    """Split body into chunks <= max_chars, preferring sentence boundaries.

    Algorithm: for each window of up to max_chars,
      1. Split at the last sentence boundary ('. ', '! ', '? ').
      2. If no sentence boundary, fall back to the last word boundary (space).
      3. If no spaces, hard cut at max_chars.

    Returns a list of non-empty chunks.
    """
    chunks = []
    pos = 0
    while pos < len(body):
        end = pos + max_chars
        if end >= len(body):
            tail = body[pos:].strip()
            if tail:
                chunks.append(tail)
            break
        window = body[pos:end]
        # 1. Try sentence boundary
        split_at = max(
            window.rfind(". "),
            window.rfind("! "),
            window.rfind("? "),
        )
        if split_at == -1 or split_at < max_chars * 0.5:
            # 2. Fall back to word boundary
            split_at = window.rfind(" ")
        if split_at == -1:
            # 3. Hard cut
            split_at = max_chars
        else:
            split_at += 1  # include the punctuation/space in chunk
        chunk = body[pos:pos + split_at].strip()
        if chunk:
            chunks.append(chunk)
        pos += split_at
    return chunks


def synthesize(text: str, voice: str, out_path: Path) -> None:
    """Stream MP3 audio for the full text to out_path.

    Renders chunks (chunk_text, sentence boundaries) in sequential batches of
    TTS_MAX_PARALLEL, appending each batch to out_path as it completes. The
    batches are the memory bound: one big pool.map would buffer every
    completed chunk's MP3 in its futures (the first v3.8 deploy OOM-killed
    the 1GB VM that way at 69 chunks); a batch holds at most ~12 x ~4MB.
    pool.map preserves order within a batch and batches run sequentially, so
    the file is in input order.

    Rate limit: the batch size bounds the burst, not requests/min (W workers
    at T seconds/call sustain W*60/T req/min, and per-call latency isn't
    promised); the correctness guarantee is the client's 429 retry with
    backoff (max_retries=5, honors Retry-After).

    Naive byte append works because tts-1 MP3 frames are self-contained.
    """
    chunks = chunk_text(text, TTS_CHAR_LIMIT)

    def render_one(chunk: str) -> bytes:
        response = openai_client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=chunk,
        )
        return response.content

    with out_path.open("wb") as f:
        with ThreadPoolExecutor(max_workers=TTS_MAX_PARALLEL) as pool:
            for i in range(0, len(chunks), TTS_MAX_PARALLEL):
                batch = chunks[i:i + TTS_MAX_PARALLEL]
                for part in pool.map(render_one, batch):
                    f.write(part)


def process(url, secret, data_dir, slug=None, *, text=None, title=None):
    """Narrate an article into an episode.

    URL mode (text is None): fetch and extract the article at `url`.
    Text mode (text is not None): narrate the supplied `text` directly with the
    given `title`, skipping the fetch, the paywall check, and the minimum-length
    guard (the caller has vouched for real content). `url`, if any, is only the
    episode's source link, never fetched.
    """
    source_url = url or ""
    if slug is None:
        slug = storage.write_pending_episode(data_dir, secret, source_url=source_url)
    try:
        if text is not None:
            episode_title, body = title, text
        else:
            episode_title, body = fetch_article(url)
            if len(body) < MIN_BODY_CHARS:
                raise FetchError(
                    f"Could only extract a snippet ({len(body)} characters) from "
                    f"{urlparse(url).netloc}. The article may be paywalled."
                )
        if len(body) > MAX_BODY_CHARS:
            raise ValueError(
                f"Article too long: {len(body):,} chars (limit: {MAX_BODY_CHARS:,}). "
                f"Try sharing a shorter article."
            )
        # Write total_chunks so the settings page can show smooth % progress.
        chunks = chunk_text(body, TTS_CHAR_LIMIT)
        storage.update_pending_episode(
            data_dir, secret, slug, total_chunks=len(chunks),
        )
        settings = storage.get_settings(data_dir, secret)
        tmp_audio = data_dir / secret / f"{slug}.mp3.tmp"
        try:
            synthesize(body, settings["voice"], tmp_audio)
            description = _excerpt(body, DESCRIPTION_EXCERPT_CHARS)
            storage.write_episode(
                data_dir, secret, slug=slug,
                title=episode_title, source_url=source_url, audio_path=tmp_audio,
                description=description,
            )
        finally:
            # On success the rename already consumed the tmp; on failure this
            # removes the partial file (the outer except records the episode
            # as failed).
            tmp_audio.unlink(missing_ok=True)
    except Exception as e:
        log.exception("ingest failed user=%s url=%s", secret[:6], url)
        storage.write_failed_episode(
            data_dir, secret, slug=slug,
            source_url=source_url, error=str(e)[:200],
        )
