import logging
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

openai_client = OpenAI()  # reads OPENAI_API_KEY from env

TTS_CHAR_LIMIT = 4000
TTS_MODEL = "tts-1"
DESCRIPTION_EXCERPT_CHARS = 200
TITLE_FETCH_TIMEOUT_S = 5.0
MAX_BODY_CHARS = 100_000  # ~50 min of TTS audio, ~$1.50 max cost per article


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


def synthesize(text: str, voice: str) -> bytes:
    """Generate MP3 audio for the full text.

    Chunks at sentence boundaries (via chunk_text) and issues ALL TTS calls in
    parallel via ThreadPoolExecutor. Returns concatenated MP3 bytes — order is
    preserved by pool.map() regardless of completion order.

    Naive byte concat works because tts-1 MP3 frames are self-contained.
    """
    chunks = chunk_text(text, TTS_CHAR_LIMIT)
    if not chunks:
        return b""

    def render_one(chunk: str) -> bytes:
        response = openai_client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=chunk,
        )
        return response.content

    # max_workers=len(chunks) → one worker per chunk, no bound. Worst-case 25
    # concurrent calls (100k char cap / 4k per chunk), well under OpenAI's
    # tier-1 limit of 50 req/min.
    with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
        parts = list(pool.map(render_one, chunks))
    return b"".join(parts)


def process(url: str, secret: str, data_dir: Path, slug: str | None = None) -> None:
    if slug is None:
        slug = storage.write_pending_episode(data_dir, secret, source_url=url)
    try:
        title, body = fetch_article(url)
        if len(body) > MAX_BODY_CHARS:
            raise ValueError(
                f"Article too long: {len(body):,} chars (limit: {MAX_BODY_CHARS:,}). "
                f"Try sharing a shorter article."
            )
        # Write total_chunks so the settings page can show smooth % progress.
        # chunk_text runs again inside synthesize — small re-cost (<10ms on 50k chars),
        # avoids changing synthesize's public signature.
        chunks = chunk_text(body, TTS_CHAR_LIMIT)
        storage.update_pending_episode(
            data_dir, secret, slug, total_chunks=len(chunks),
        )
        settings = storage.get_settings(data_dir, secret)
        audio = synthesize(body, settings["voice"])
        description = _excerpt(body, DESCRIPTION_EXCERPT_CHARS)
        storage.write_episode(
            data_dir, secret, slug=slug,
            title=title, source_url=url, audio=audio,
            description=description,
        )
    except Exception as e:
        log.exception("ingest failed user=%s url=%s", secret[:6], url)
        storage.write_failed_episode(
            data_dir, secret, slug=slug,
            source_url=url, error=str(e)[:200],
        )
