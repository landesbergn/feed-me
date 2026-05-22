from email.utils import format_datetime
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["xml"]),
)


def render_feed(*, feed_url: str, audio_base: str, episodes: list[dict]) -> str:
    ready = [e for e in episodes if e.get("has_audio")]
    enriched = [
        {
            **e,
            "pub_date": format_datetime(
                datetime.fromtimestamp(e["ts"], tz=timezone.utc)
            ),
        }
        for e in ready
    ]
    template = _env.get_template("feed.xml")
    return template.render(
        feed_url=feed_url,
        audio_base=audio_base,
        episodes=enriched,
    )
