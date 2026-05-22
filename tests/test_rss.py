from xml.etree import ElementTree as ET

import rss


def _parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def test_render_feed_has_required_structure():
    xml = rss.render_feed(
        feed_url="https://feed-me.app/u/abc/feed.xml",
        audio_base="https://feed-me.app/u/abc/audio",
        episodes=[],
    )
    root = _parse(xml)
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"
    channel = root.find("channel")
    assert channel is not None
    assert channel.findtext("title") == "Feed Me"


def test_render_feed_emits_ready_episodes_in_order():
    eps = [
        {"slug": "s1", "title": "Newer", "url": "https://a", "ts": 200,
         "mtime": 200.0, "has_audio": True},
        {"slug": "s2", "title": "Older", "url": "https://b", "ts": 100,
         "mtime": 100.0, "has_audio": True},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.app/u/abc/feed.xml",
        audio_base="https://feed-me.app/u/abc/audio",
        episodes=eps,
    )
    root = _parse(xml)
    items = root.findall("channel/item")
    assert len(items) == 2
    assert items[0].findtext("title") == "Newer"
    assert items[1].findtext("title") == "Older"
    enc = items[0].find("enclosure")
    assert enc is not None
    assert enc.attrib["url"] == "https://feed-me.app/u/abc/audio/s1.mp3"
    assert enc.attrib["type"] == "audio/mpeg"


def test_render_feed_omits_failed_episodes():
    eps = [
        {"slug": "good", "title": "OK", "url": "https://a", "ts": 1,
         "mtime": 1.0, "has_audio": True},
        {"slug": "bad", "title": None, "url": "https://b", "ts": 2,
         "mtime": 2.0, "has_audio": False, "error": "boom"},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.app/u/abc/feed.xml",
        audio_base="https://feed-me.app/u/abc/audio",
        episodes=eps,
    )
    items = _parse(xml).findall("channel/item")
    assert len(items) == 1
    assert items[0].findtext("title") == "OK"
