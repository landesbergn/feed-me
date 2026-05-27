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
        storage.write_episode(
            data_dir, secret, slug=slug,
            title=title, source_url=url, audio=audio,
        )
    except Exception as e:
        log.exception("ingest failed user=%s url=%s", secret[:6], url)
        storage.write_failed_episode(
            data_dir, secret, slug=slug,
            source_url=url, error=str(e)[:200],
        )
