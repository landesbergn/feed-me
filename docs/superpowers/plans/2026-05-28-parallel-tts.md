# Parallel TTS (v1.8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut ingest wall time from ~10 min to ~90s for long articles by issuing all TTS calls in parallel via `ThreadPoolExecutor`, replacing the sequential `for` loop in `synthesize()`.

**Architecture:** Two tasks: (1) refactor `synthesize` to use `ThreadPoolExecutor` with `pool.map()` for order-preserving parallelism, add a regression test that verifies order survives out-of-order completion; (2) deploy + tag.

**Tech Stack:** Pure stdlib (`concurrent.futures.ThreadPoolExecutor`). No new dependencies. Spec: `docs/superpowers/specs/2026-05-27-parallel-tts.html`.

> **Spec note:** The order-preservation test in the spec's §4 has a bug (the synthetic body is too short to produce multiple chunks, so the test would pass even if parallelism reverted). This plan uses a corrected version that monkey-patches `chunk_text` to force multiple known chunks. Caught by advisor review on 2026-05-27.

---

## File Structure

```
feed-me/
  ingest.py              # synthesize: for-loop → ThreadPoolExecutor.map
  tests/
    test_ingest.py       # +test_synthesize_preserves_chunk_order_under_parallelism
```

Only two files change. No new dependencies.

---

## Task 1: Parallelize `synthesize` + add order-preservation test

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/ingest.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_ingest.py`

- [ ] **Step 1: Append the failing test to `/Users/noah/Desktop/feed-me/tests/test_ingest.py`**

```python
def test_synthesize_preserves_chunk_order_under_parallelism(monkeypatch):
    """When TTS calls complete out of order, output bytes are still in input order.

    Monkey-patches chunk_text to return a known list (bypassing chunking heuristics)
    so we can directly verify that synthesize concatenates in INPUT order even when
    later chunks finish their TTS call first.
    """
    import time

    # Force chunk_text to return three known inputs.
    known_chunks = ["alpha", "bravo", "charlie"]
    monkeypatch.setattr(ingest, "chunk_text", lambda body, max_chars: known_chunks)

    # Fake TTS: returns the input text as bytes, but sleeps inversely to chunk index
    # so the FIRST input finishes LAST (forcing out-of-order completion).
    class OrderingFake:
        def __init__(self):
            self.calls = []
        @property
        def audio(self):
            return self
        @property
        def speech(self):
            return self
        def create(self, *, model, voice, input):
            self.calls.append(input)
            idx = known_chunks.index(input)
            # Earlier chunks sleep longer → finish later
            time.sleep(0.05 * (len(known_chunks) - idx))
            return type("R", (), {"content": input.encode("utf-8")})()

    monkeypatch.setattr(ingest, "openai_client", OrderingFake())

    audio = ingest.synthesize("any body", "shimmer")

    # Bytes must be in INPUT order (alpha, bravo, charlie), not completion order
    # (charlie finished first, alpha finished last).
    assert audio == b"alphabravocharlie"
```

- [ ] **Step 2: Run the new test, verify it FAILS today**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_ingest.py::test_synthesize_preserves_chunk_order_under_parallelism -v
```

Expected: **PASS** today because the current sequential `synthesize` calls the fake in input order, so it naturally returns bytes in input order. This means the test is correct but doesn't catch the regression by itself — that's fine, the test's job is to prevent FUTURE regressions to completion-ordering.

Note for transparency: this is a "characterization test" — it documents the invariant rather than driving a fix. The actual win (parallelism) is observable via timing, not via this test. Continue.

- [ ] **Step 3: Replace `synthesize` in `/Users/noah/Desktop/feed-me/ingest.py`**

Add the import near the top of the file (with other stdlib imports):

```python
from concurrent.futures import ThreadPoolExecutor
```

Find the existing `synthesize` function. Replace it entirely with:

```python
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
```

The change vs. v1.7: the `for chunk in chunks: parts.append(...)` loop is replaced with `ThreadPoolExecutor` + `pool.map()`. Everything else (signature, chunking, byte concat) is identical.

- [ ] **Step 4: Run all tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: all tests pass. Specifically:
- `test_synthesize_long_text_calls_tts_for_each_chunk`: still passes — chunk count + byte concat both order-agnostic
- `test_synthesize_short_text_calls_tts_once`: still passes — 1 chunk → 1 worker
- `test_synthesize_preserves_chunk_order_under_parallelism`: passes (the new test from Step 1)
- All `process` tests: still pass
- Total: 94 tests (was 93, plus the new one)

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add ingest.py tests/test_ingest.py && git commit -m "feat(ingest): parallelize TTS calls via ThreadPoolExecutor

Replaces the sequential for-loop in synthesize() with ThreadPoolExecutor
+ pool.map(). All chunks render in parallel; pool.map() preserves input
order so concatenated bytes are still chronological.

For the 50-min Notion article (~13 chunks), this should cut ingest from
~10 min wall time to ~60-90s. Worst-case 25 chunks (100k char cap)
stays well under OpenAI's 50 req/min tier-1 rate limit, so no bounded
concurrency needed.

Adds test_synthesize_preserves_chunk_order_under_parallelism as a
regression guard against switching back to completion-order output."
```

---

## Task 2: Deploy v1.8 + tag

**Files:** none (deploy + CHANGELOG + tag)

- [ ] **Step 1: Deploy**

```bash
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

Expected: build succeeds.

- [ ] **Step 2: Re-share the Notion article and time it**

On your iPhone, share `https://colossus.com/article/inside-notion/` again via the Feed Me Shortcut. Note the time you tap Share. Watch the polling table for the row to flip from Pending → Ready.

Expected: 60-90 seconds wall time, down from 10:02 in v1.7. The audio file should still be ~60 MB / 50 min — same content, faster generation.

If the wall time is unchanged (still 10 min) or if you see a flurry of 429 errors in `~/.fly/bin/fly logs`, something's wrong; tell me before tagging.

- [ ] **Step 3: Update CHANGELOG and tag v1.8**

Insert this entry at the top of `/Users/noah/Desktop/feed-me/CHANGELOG.md` (above the v1.7 entry):

```markdown
## v1.8 — 2026-05-28

Parallel TTS — 10 min → ~90s for long articles:

- `synthesize()` now issues all chunked TTS calls in parallel via `ThreadPoolExecutor` instead of a sequential `for` loop. `pool.map()` preserves input order so MP3 bytes are still concatenated chronologically.
- No bounded concurrency: worst-case 25 chunks (100k char cap) stays under OpenAI's 50 req/min tier-1 rate limit.
- New regression test guards against switching back to completion-order output.
- Spec: `docs/superpowers/specs/2026-05-27-parallel-tts.html`
```

Then:

```bash
cd /Users/noah/Desktop/feed-me && git add CHANGELOG.md && git commit -m "release: v1.8 parallel TTS" && git tag v1.8
```

---

## Self-Review

### Spec coverage

| Spec section | Implementing task |
|---|---|
| §2 ThreadPoolExecutor in synthesize | Task 1 step 3 |
| §3 Implementation: `pool.map()` for order, unbounded concurrency | Task 1 step 3 (max_workers=len(chunks)) |
| §3 Failure behavior (one chunk fails → episode fails) | Implicit — pool.map() re-raises first exception, propagates to process()'s existing except |
| §3 Memory note (~125-200MB peak) | Implicit — no code change needed; documented in spec |
| §4 Existing tests still pass | Task 1 step 4 (full suite run) |
| §4 New order-preservation test | Task 1 step 1 (CORRECTED version vs. spec's flawed draft — see plan header note) |
| §7 Acceptance: <2 min wall time for Notion article | Task 2 step 2 |
| §7 No new dependencies | Pure stdlib; verified |

All sections covered. Spec's §5 (out of scope: retry, progress UI, async refactor, streaming) and §6 (future) are correctly absent from this plan.

### Placeholder scan

Scanned for "TBD", "TODO", "fill in", "appropriate error handling", "similar to Task N". None found. Every code block is complete. Step 2 note about "characterization test" is honest framing of what the test actually proves, not a placeholder.

### Type consistency

- `synthesize(text: str, voice: str) -> bytes` — unchanged signature.
- `chunk_text(body, max_chars)` — unchanged, still returns `list[str]`.
- `ThreadPoolExecutor(max_workers=int)` — stdlib.
- `pool.map(callable, iterable)` — returns iterator preserving input order.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-parallel-tts.md`.

Two tasks, ~10 minutes of focused subagent work plus a manual iPhone re-share to verify the wall-time improvement.
