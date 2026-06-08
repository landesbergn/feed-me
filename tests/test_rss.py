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
    root = _parse(xml)
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    item = root.find("channel/item")
    desc = item.findtext("description")
    # excerpt preserved
    assert "First few sentences of the article…" in desc
    # clickable links present (entity-escaped HTML → ET un-escapes to literal tags)
    assert '<a href="https://a">' in desc
    assert "Generated with" in desc and "Feed Me" in desc
    # link back to the user's feed page (feed_url minus /feed.xml)
    assert "https://feed-me.xyz/u/abc" in desc
    # itunes:summary is plain text (no HTML tags), with the excerpt + URLs
    summary = item.find("itunes:summary", ns).text
    assert "First few sentences of the article…" in summary
    assert "https://a" in summary
    assert "<a href" not in summary


def test_render_feed_item_without_excerpt_still_has_links():
    """When an item has no description, links are still present."""
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
    desc = item.findtext("description")
    assert '<a href="https://example.com/a">' in desc
    assert "Generated with" in desc


def test_render_feed_channel_has_return_link_and_handles_amp_urls():
    eps = [
        {"slug": "s1", "title": "A", "ts": 1, "mtime": 1.0,
         "has_audio": True, "audio_bytes": 10,
         "url": "https://x.com/a?u=1&v=2", "description": "body"},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/SEKRET/feed.xml",
        audio_base="https://feed-me.xyz/u/SEKRET/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    # Must be well-formed XML despite the & in the article URL.
    root = _parse(xml)
    channel = root.find("channel")
    chan_desc = channel.findtext("description")
    assert "Your personal podcast" in chan_desc
    assert "https://feed-me.xyz/u/SEKRET" in chan_desc
    assert '<a href="https://feed-me.xyz/u/SEKRET">' in chan_desc
    # The episode link preserves the full article URL (HTML-level &amp; for the &).
    item_desc = root.find("channel/item").findtext("description")
    assert "https://x.com/a?u=1" in item_desc
    assert "v=2" in item_desc


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


def test_render_feed_omits_original_article_when_url_empty():
    eps = [
        {"slug": "t1", "title": "From text", "url": "", "ts": 5,
         "mtime": 5.0, "has_audio": True, "audio_bytes": 10,
         "description": "An excerpt."},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    assert "Original article" not in xml
    assert "Generated with" in xml          # the other description line stays
    assert "An excerpt." in xml


def test_render_feed_includes_original_article_when_url_present():
    eps = [
        {"slug": "u1", "title": "From url", "url": "https://example.com/x", "ts": 6,
         "mtime": 6.0, "has_audio": True, "audio_bytes": 10,
         "description": "An excerpt."},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    assert "Original article" in xml
    assert "https://example.com/x" in xml
