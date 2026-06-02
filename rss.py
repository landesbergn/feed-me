import html
from email.utils import format_datetime
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["xml"]),
)

CHANNEL_BLURB = "Your personal podcast of articles you've saved with Feed Me."


def _home_url_from_feed(feed_url: str) -> str:
    """The user's feed page (/u/{secret}) — feed_url minus the /feed.xml suffix."""
    suffix = "/feed.xml"
    return feed_url[: -len(suffix)] if feed_url.endswith(suffix) else feed_url


def _episode_description_html(excerpt: str, article_url: str, home_url: str) -> str:
    parts = []
    if excerpt:
        parts.append(html.escape(excerpt))
    parts.append(
        f'Original article: <a href="{html.escape(article_url, quote=True)}">'
        f"{html.escape(article_url)}</a>"
    )
    parts.append(
        f'Generated with <a href="{html.escape(home_url, quote=True)}">Feed Me</a>'
    )
    return "<br/><br/>".join(parts)


def _episode_description_text(excerpt: str, article_url: str, home_url: str) -> str:
    lines = []
    if excerpt:
        lines.append(excerpt)
    lines.append(f"Original article: {article_url}")
    lines.append(f"Generated with Feed Me: {home_url}")
    return "\n\n".join(lines)


def render_feed(*, feed_url: str, audio_base: str, cover_url: str, episodes: list[dict]) -> str:
    home_url = _home_url_from_feed(feed_url)
    ready = [e for e in episodes if e.get("has_audio")]
    enriched = []
    for e in ready:
        excerpt = e.get("description") or ""
        enriched.append({
            **e,
            "pub_date": format_datetime(
                datetime.fromtimestamp(e["ts"], tz=timezone.utc)
            ),
            "description_html": _episode_description_html(excerpt, e["url"], home_url),
            "description_text": _episode_description_text(excerpt, e["url"], home_url),
        })
    channel_description_html = (
        f"{html.escape(CHANNEL_BLURB)}<br/><br/>"
        f'Your feed: <a href="{html.escape(home_url, quote=True)}">{html.escape(home_url)}</a>'
    )
    channel_description_text = f"{CHANNEL_BLURB}\n\nYour feed: {home_url}"
    template = _env.get_template("feed.xml")
    return template.render(
        feed_url=feed_url,
        audio_base=audio_base,
        cover_url=cover_url,
        episodes=enriched,
        channel_description_html=channel_description_html,
        channel_description_text=channel_description_text,
    )
