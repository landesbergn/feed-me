from xml.etree import ElementTree as ET

import rss


def _parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def test_render_feed_has_required_structure():
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=[],
    )
    root = _parse(xml)
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"
    channel = root.find("channel")
    assert channel is not None
    assert channel.findtext("title") == "Feed Me"
    # New description text in v1.4
    desc = channel.findtext("description")
    assert "Your personal podcast" in desc
    assert "Feed Me" in desc


def test_render_feed_emits_ready_episodes_in_order():
    eps = [
        {"slug": "s1", "title": "Newer", "url": "https://a", "ts": 200,
         "mtime": 200.0, "has_audio": True, "audio_bytes": 100},
        {"slug": "s2", "title": "Older", "url": "https://b", "ts": 100,
         "mtime": 100.0, "has_audio": True, "audio_bytes": 200},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    root = _parse(xml)
    items = root.findall("channel/item")
    assert len(items) == 2
    assert items[0].findtext("title") == "Newer"
    assert items[1].findtext("title") == "Older"
    enc = items[0].find("enclosure")
    assert enc is not None
    assert enc.attrib["url"] == "https://feed-me.xyz/u/abc/audio/s1.mp3"
    assert enc.attrib["type"] == "audio/mpeg"
    assert enc.attrib["length"] == "100"


def test_render_feed_omits_failed_episodes():
    eps = [
        {"slug": "good", "title": "OK", "url": "https://a", "ts": 1,
         "mtime": 1.0, "has_audio": True, "audio_bytes": 50},
        {"slug": "bad", "title": None, "url": "https://b", "ts": 2,
         "mtime": 2.0, "has_audio": False, "error": "boom"},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    items = _parse(xml).findall("channel/item")
    assert len(items) == 1
    assert items[0].findtext("title") == "OK"


def test_render_feed_includes_itunes_image_and_summary():
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=[],
    )
    # Resolve the itunes namespace for findall
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    root = _parse(xml)
    channel = root.find("channel")

    image_el = channel.find("itunes:image", ns)
    assert image_el is not None
    assert image_el.attrib["href"] == "https://feed-me.xyz/cover.jpg"

    summary_el = channel.find("itunes:summary", ns)
    assert summary_el is not None
    assert "Your personal podcast" in summary_el.text


def test_render_feed_includes_atom_link_self():
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=[],
    )
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    }
    root = _parse(xml)
    channel = root.find("channel")
    atom_link = channel.find("atom:link", ns)
    assert atom_link is not None
    assert atom_link.attrib["rel"] == "self"
    assert atom_link.attrib["href"] == "https://feed-me.xyz/u/abc/feed.xml"
    assert atom_link.attrib["type"] == "application/rss+xml"


def test_render_feed_includes_itunes_type_episodic():
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=[],
    )
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    root = _parse(xml)
    channel = root.find("channel")
    type_el = channel.find("itunes:type", ns)
    assert type_el is not None
    assert type_el.text == "episodic"


def test_render_feed_per_item_description_and_summary():
    eps = [
        {"slug": "s1", "title": "Article", "url": "https://a", "ts": 1,
         "mtime": 1.0, "has_audio": True, "audio_bytes": 42,
         "description": "First few sentences of the article…"},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    root = _parse(xml)
    item = root.find("channel/item")
    assert item.findtext("description") == "First few sentences of the article…"
    assert item.find("itunes:summary", ns).text == "First few sentences of the article…"


def test_render_feed_per_item_description_falls_back_to_url():
    """When an item has no description (pending case), description = source URL."""
    eps = [
        {"slug": "s1", "title": "X", "url": "https://example.com/a", "ts": 1,
         "mtime": 1.0, "has_audio": True, "audio_bytes": 42},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    root = _parse(xml)
    item = root.find("channel/item")
    assert item.findtext("description") == "https://example.com/a"


def test_render_feed_enclosure_uses_real_audio_bytes():
    eps = [
        {"slug": "s1", "title": "X", "url": "https://a", "ts": 1,
         "mtime": 1.0, "has_audio": True, "audio_bytes": 137154,
         "description": "x"},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    root = _parse(xml)
    enc = root.find("channel/item/enclosure")
    assert enc.attrib["length"] == "137154"
