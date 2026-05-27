import logging
from pathlib import Path

import httpx
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
        )
    },
    follow_redirects=True,
)

openai_client = OpenAI()  # reads OPENAI_API_KEY from env

TTS_CHAR_LIMIT = 4000
TTS_MODEL = "tts-1"
DESCRIPTION_EXCERPT_CHARS = 200
TITLE_FETCH_TIMEOUT_S = 5.0


def fetch_article(url: str) -> tuple[str, str]:
    resp = http_client.get(url)
    resp.raise_for_status()
    doc = Document(resp.text)
    summary_html = doc.summary()
    summary_elem = lxml_html.fromstring(summary_html)

    # Try to extract h1 as title, fall back to page title
    h1s = summary_elem.xpath('.//h1')
    if h1s:
        title = h1s[0].text_content().strip()
    else:
        title = doc.short_title() or doc.title()

    # Extract body, excluding the h1 we already extracted as title
    body = summary_elem.text_content().strip()
    # Remove the h1 text from body if it's at the start
    if title and body.startswith(title):
        body = body[len(title):].strip()
    body = "\n\n".join(line.strip() for line in body.splitlines() if line.strip())
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


def synthesize(text: str, voice: str) -> bytes:
    response = openai_client.audio.speech.create(
        model=TTS_MODEL,
        voice=voice,
        input=text[:TTS_CHAR_LIMIT],
    )
    return response.content


def process(url: str, secret: str, data_dir: Path) -> None:
    slug = storage.write_pending_episode(data_dir, secret, source_url=url)
    try:
        title, body = fetch_article(url)
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
