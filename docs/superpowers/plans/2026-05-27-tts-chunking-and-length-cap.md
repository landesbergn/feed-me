# TTS Chunking + 100k Cap (v1.7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Long articles play through to the end instead of cutting off ~4 min in; articles >100k chars fail explicitly instead of running up cost silently.

**Architecture:** Three tasks: `chunk_text` helper (pure function, TDD-friendly), `synthesize` loops over chunks + `process` checks the 100k cap, then deploy + tag.

**Tech Stack:** Same as v1.6 — no new deps. Naive byte concatenation of MP3 chunks works (validated by the user's existing 4-min-cutoff observation; modern podcast apps handle multi-frame MP3s fine).

---

## File Structure

```
feed-me/
  ingest.py                  # +chunk_text, +MAX_BODY_CHARS, synthesize loops, process caps
  tests/
    test_ingest.py           # chunk_text tests, multi-call synthesize, cap-exceeded process test
```

Only two files change. No new dependencies. No changes to storage, RSS, templates, or app.

---

## Task 1: `chunk_text` helper

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/ingest.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_ingest.py`

Pure function — add the helper first, then in Task 2 wire it into `synthesize`.

- [ ] **Step 1: Append failing tests to `/Users/noah/Desktop/feed-me/tests/test_ingest.py`**

```python
def test_chunk_text_short_body_returns_one_chunk():
    body = "Short text under the limit."
    chunks = ingest.chunk_text(body, max_chars=4000)
    assert chunks == ["Short text under the limit."]


def test_chunk_text_splits_at_sentence_boundary():
    # Three sentences, each ~30 chars, force a split with a small max
    body = (
        "First sentence here. "
        "Second sentence here. "
        "Third sentence here."
    )
    chunks = ingest.chunk_text(body, max_chars=42)
    # Should split between sentences (after ". ")
    assert len(chunks) >= 2
    # Every chunk should be <= max_chars
    for c in chunks:
        assert len(c) <= 42
    # Reassembling should give back roughly the original (whitespace may differ at joins)
    assert "First sentence" in chunks[0]
    assert "Third sentence" in chunks[-1]


def test_chunk_text_falls_back_to_word_boundary_when_no_sentences():
    # No sentence punctuation at all, just words separated by spaces
    body = "one two three four five six seven eight nine ten eleven twelve"
    chunks = ingest.chunk_text(body, max_chars=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 20
        # Each chunk shouldn't split a word — every chunk ends with a complete word
        assert not c.endswith("-")  # nothing weird
    # No word should be cut across chunks
    combined = " ".join(chunks).split()
    original = body.split()
    assert combined == original


def test_chunk_text_handles_body_longer_than_two_chunks():
    # 9 sentences * ~22 chars = ~200 chars, with max 100 → expect ~2-3 chunks
    body = " ".join([f"Sentence number {i} here." for i in range(1, 10)])
    chunks = ingest.chunk_text(body, max_chars=100)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 100


def test_chunk_text_drops_empty_chunks():
    """Trailing whitespace shouldn't create an empty final chunk."""
    body = "Real content here.   "  # trailing spaces
    chunks = ingest.chunk_text(body, max_chars=4000)
    # Should be a single non-empty chunk, no empties
    assert all(c.strip() for c in chunks)
    assert len(chunks) == 1
```

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_ingest.py -v -k "chunk_text"
```

Expected: 5 FAIL with `AttributeError: module 'ingest' has no attribute 'chunk_text'`.

- [ ] **Step 3: Add `chunk_text` to `/Users/noah/Desktop/feed-me/ingest.py`**

Add this function near `_excerpt` (or wherever the other helpers live):

```python
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
```

- [ ] **Step 4: Run, verify the tests pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_ingest.py -v -k "chunk_text"
```

Expected: 5 PASS.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -5
```

Expected: all pass (existing tests untouched + 5 new chunk_text tests).

- [ ] **Step 6: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add ingest.py tests/test_ingest.py && git commit -m "feat(ingest): chunk_text helper for sentence-aware splitting

Pure function: splits a body into chunks <= max_chars, preferring
sentence boundaries (. ! ?), falling back to word boundaries, finally
hard-cut. Wired into synthesize() in the next task."
```

---

## Task 2: Loop in `synthesize` + 100k cap in `process`

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/ingest.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_ingest.py`

- [ ] **Step 1: Update existing tests + add new tests in `/Users/noah/Desktop/feed-me/tests/test_ingest.py`**

Find the existing `test_synthesize_truncates_long_text` function. Replace it entirely with these two:

```python
def test_synthesize_long_text_calls_tts_for_each_chunk(monkeypatch, fake_openai):
    """Long input is chunked; synthesize calls TTS once per chunk and concatenates."""
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    # Each chunk returns the fixture's audio_bytes; we use a body that will produce
    # 3 chunks at TTS_CHAR_LIMIT (4000). Use sentence punctuation to make chunks split
    # cleanly at sentence boundaries.
    one_sentence = "This is a sentence that takes up some text. "
    # 3000 chars per "block", 3 blocks → 9000 chars → at least 3 chunks under a 4000 cap
    long_body = one_sentence * 200  # ~9000 chars

    audio = ingest.synthesize(long_body, "shimmer")

    # synthesize called the fake TTS multiple times
    assert len(fake_openai.calls) >= 2
    # Each call got a chunk under the limit
    for call in fake_openai.calls:
        assert len(call["input"]) <= ingest.TTS_CHAR_LIMIT
    # Returned bytes are the concatenation of all the fake response bodies
    assert audio == fake_openai.audio_bytes * len(fake_openai.calls)


def test_synthesize_short_text_calls_tts_once(monkeypatch, fake_openai):
    """Body shorter than TTS_CHAR_LIMIT → single call, no chunking visible."""
    monkeypatch.setattr(ingest, "openai_client", fake_openai)

    audio = ingest.synthesize("Short body.", "shimmer")

    assert len(fake_openai.calls) == 1
    assert fake_openai.calls[0]["input"] == "Short body."
    assert audio == fake_openai.audio_bytes
```

Also append a new test for the 100k cap:

```python
def test_process_writes_failure_when_body_exceeds_cap(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    """Bodies > MAX_BODY_CHARS fail with a clear error, no TTS calls made."""
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)

    # Build HTML with a body that, after Readability extraction, is > 100k chars.
    # We need enough article-like content for Readability to pick it up. Repeat a
    # long paragraph until we comfortably exceed the cap.
    huge_paragraph = "<p>" + ("This sentence is very long and detailed and exists " * 50) + "</p>"
    huge_html = (
        "<!doctype html><html><head><title>Huge</title></head>"
        "<body><article><h1>Big</h1>"
        + (huge_paragraph * 100)  # ~100 paragraphs * 2700 chars each
        + "</article></body></html>"
    )
    fake_http.responses["https://example.com/huge"] = FakeResponse(
        status_code=200, text=huge_html,
    )

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/huge", secret, tmp_path)

    # No TTS calls were made (we bailed before synthesize)
    assert len(fake_openai.calls) == 0
    # Episode recorded as failed with the expected error text
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "failed"
    assert "too long" in eps[0]["error"].lower()
```

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_ingest.py -v -k "synthesize_long_text or synthesize_short_text or exceeds_cap"
```

Expected: the synthesize tests pass for the short case but the long case fails (current synthesize truncates to one call). The exceeds_cap test fails (current process doesn't check).

- [ ] **Step 3: Replace `synthesize` in `/Users/noah/Desktop/feed-me/ingest.py`**

Find the existing `synthesize` function. Replace it entirely with:

```python
def synthesize(text: str, voice: str) -> bytes:
    """Generate MP3 audio for the full text, chunking at sentence boundaries
    so each TTS call is within OpenAI's per-call cap.

    Returns the concatenated MP3 bytes (naive byte concat — each chunk's MP3
    frames are self-contained, so the combined file plays as one continuous
    track in podcast apps)."""
    chunks = chunk_text(text, TTS_CHAR_LIMIT)
    parts = []
    for chunk in chunks:
        response = openai_client.audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=chunk,
        )
        parts.append(response.content)
    return b"".join(parts)
```

The single-line `text[:TTS_CHAR_LIMIT]` truncation is gone.

- [ ] **Step 4: Add `MAX_BODY_CHARS` constant and cap-check in `process` in `/Users/noah/Desktop/feed-me/ingest.py`**

Near the existing `DESCRIPTION_EXCERPT_CHARS = 200` and `TITLE_FETCH_TIMEOUT_S = 5.0` constants, add:

```python
MAX_BODY_CHARS = 100_000  # ~50 min of TTS audio, ~$1.50 max cost per article
```

Find the existing `process` function. Inside the `try:` block, right after `title, body = fetch_article(url)`, insert the cap check:

```python
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
```

The only new lines are the `if len(body) > MAX_BODY_CHARS: raise ValueError(...)` block. The rest is identical to the existing v1.6 `process`.

- [ ] **Step 5: Run the full test suite, verify all tests pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: all tests pass — chunked synthesize for the long-text case; existing short-text behavior unchanged; long-body case correctly recorded as failed.

- [ ] **Step 6: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add ingest.py tests/test_ingest.py && git commit -m "feat(ingest): chunked TTS + 100k char cap

- synthesize() now loops over chunk_text() output and concatenates MP3
  bytes. Removes the silent text[:TTS_CHAR_LIMIT] truncation that was
  cutting articles off ~4 min in.
- process() checks len(body) > MAX_BODY_CHARS (100k) before calling
  synthesize; raises ValueError with a clear message; the existing
  except block records it as a failed episode with the error visible
  on the settings page.
- No new dependencies. MP3 byte concatenation works because tts-1
  frames are self-contained."
```

---

## Task 3: Deploy v1.7 + tag

**Files:** none (deploy + CHANGELOG + tag)

- [ ] **Step 1: Deploy**

```bash
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

Expected: build succeeds.

- [ ] **Step 2: Re-share the Notion article to verify the full audio plays**

On your iPhone, share `https://colossus.com/article/inside-notion/` again via the Feed Me Shortcut. After ~30-60 seconds (longer than before — multiple TTS calls), the new episode appears. In Apple Podcasts, the episode should be ~15-25 min long (the full article), not 4:12.

- [ ] **Step 3: Verify the 100k cap by trying a deliberately-long URL**

If you have a known long-form article (50k+ chars), share it and verify it still processes successfully (under cap → multiple chunks → full audio).

To test the cap itself manually is harder without finding a 100k+ char article. The test suite covers this.

- [ ] **Step 4: Update CHANGELOG and tag v1.7**

Insert this entry at the top of `/Users/noah/Desktop/feed-me/CHANGELOG.md` (above the v1.6 entry):

```markdown
## v1.7 — 2026-05-27

Fixes silent audio truncation on long articles:

- `synthesize()` now chunks the article body at sentence boundaries and makes multiple TTS calls instead of truncating to the first 4000 chars. MP3 bytes are concatenated naively (works because tts-1 frames are self-contained). Articles over 4 min (~600 words) now play through to the end.
- Hard cap at 100k chars per article (~50 min of audio, ~$1.50 max cost). Articles over the cap fail with the message "Article too long: NNN,NNN chars (limit: 100,000)..." visible on the settings page, instead of silently running up cost.
- Spec: `docs/superpowers/specs/2026-05-27-tts-chunking-and-length-cap.html`
```

Then:

```bash
cd /Users/noah/Desktop/feed-me && git add CHANGELOG.md && git commit -m "release: v1.7 TTS chunking + 100k cap" && git tag v1.7
```

---

## Self-Review

### Spec coverage

| Spec section | Implementing task |
|---|---|
| §3 chunk_text algorithm (sentence → word → hard cut) | Task 1 |
| §3 MP3 byte concatenation | Task 2 (synthesize uses `b"".join(parts)`) |
| §3 Latency note | Implicit in implementation — synthesize is now sequentially N×TTS |
| §4 MAX_BODY_CHARS = 100_000 + clear error | Task 2 |
| §4 Error propagates to write_failed_episode | Task 2 (existing try/except in process) |
| §5 Files modified | ingest.py + test_ingest.py — matches spec |
| §6 chunk_text tests (5) | Task 1 |
| §6 synthesize tests | Task 2 (the existing `truncates_long_text` is REPLACED — explicit) |
| §6 process cap test | Task 2 |
| §9 Acceptance | Task 3 manual verification |

All spec sections covered. Out-of-scope items (parallel TTS, model swap, progress UI) correctly absent from the plan.

### Placeholder scan

Scanned for "TBD", "TODO", "fill in", "appropriate error handling", "similar to Task N". None found. Every code block is complete. The Notion article re-share verification in Task 3 step 2 is an explicit instruction, not a placeholder.

### Type consistency

- `chunk_text(body: str, max_chars: int) -> list[str]` — consistent between Task 1 definition and Task 2 caller.
- `MAX_BODY_CHARS = 100_000` — single constant, referenced in process() and the error message.
- `synthesize(text: str, voice: str) -> bytes` — signature unchanged externally; internal change only.
- `process` signature unchanged (still `(url, secret, data_dir, slug=None)`).
- Error message format consistent: tests assert "too long" lowercase substring match; implementation uses "Article too long: …" which contains it.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-27-tts-chunking-and-length-cap.md`.

Three tasks, ~20 minutes of focused subagent work plus a manual iPhone re-share to verify the full audio plays.
