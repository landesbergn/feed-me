# Pending Progress Indicator (v2.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a smooth, monotonically-increasing percent next to the Pending chip so friends can see ingest is alive and roughly how far along it is.

**Architecture:** Three tasks — (1) backend `storage.update_pending_episode` + `process` writes `total_chunks`; (2) template adds `data-ts`/`data-chunks` attrs + JS ticker; (3) deploy + tag.

**Tech Stack:** Pure Python + vanilla JS. No new deps. Spec: `docs/superpowers/specs/2026-05-29-pending-progress-indicator.html`.

---

## File Structure

```
feed-me/
  storage.py                       # +update_pending_episode()
  ingest.py                        # process() writes total_chunks after fetch_article
  templates/
    _episodes_section.html         # +data-ts/data-chunks on pending status cell
    settings.html                  # +JS ticker block
  tests/
    test_storage.py                # +2 tests for update_pending_episode
    test_ingest.py                 # +1 test that process writes total_chunks during pending
    test_app.py                    # +1 test for data attrs in rendered HTML
```

---

## Task 1: `storage.update_pending_episode` + `process` writes `total_chunks`

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/storage.py`
- Modify: `/Users/noah/Desktop/feed-me/ingest.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_storage.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_ingest.py`

- [ ] **Step 1: Append failing storage tests to `/Users/noah/Desktop/feed-me/tests/test_storage.py`**

```python
def test_update_pending_episode_sets_total_chunks(tmp_path):
    """Updating total_chunks on an existing pending record preserves other fields."""
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret,
        source_url="https://example.com/x",
        title="Some Article",
    )

    storage.update_pending_episode(tmp_path, secret, slug, total_chunks=13)

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "pending"
    assert eps[0]["title"] == "Some Article"  # preserved
    assert eps[0]["url"] == "https://example.com/x"  # preserved
    assert eps[0]["total_chunks"] == 13


def test_update_pending_episode_noop_when_missing(tmp_path):
    """Updating a non-existent slug returns without raising and doesn't create a file."""
    secret = storage.create_user(tmp_path)

    # Should not raise
    storage.update_pending_episode(tmp_path, secret, "missing_slug", total_chunks=5)

    eps = storage.list_episodes(tmp_path, secret)
    assert eps == []
    # No phantom files created
    assert not (tmp_path / secret / "missing_slug.json").exists()
```

- [ ] **Step 2: Append a failing ingest test to `/Users/noah/Desktop/feed-me/tests/test_ingest.py`**

```python
def test_process_writes_total_chunks_before_synthesize(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    """process() must write total_chunks to the pending record BEFORE calling synthesize,
    so the polling endpoint can pick it up while the worker is still running."""
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    fake_http.responses["https://example.com/t"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )

    secret = storage.create_user(tmp_path)

    # Monkey-patch synthesize to observe storage at the moment it's called.
    # At that moment the pending record MUST have total_chunks set.
    observed_total_chunks = []
    real_synthesize = ingest.synthesize
    def observing_synthesize(text, voice):
        eps = storage.list_episodes(tmp_path, secret)
        # Find the pending row for our URL and capture its total_chunks
        for e in eps:
            if e.get("status") == "pending" and e.get("url") == "https://example.com/t":
                observed_total_chunks.append(e.get("total_chunks"))
                break
        return real_synthesize(text, voice)
    monkeypatch.setattr(ingest, "synthesize", observing_synthesize)

    ingest.process("https://example.com/t", secret, tmp_path)

    # synthesize was called once, and at that moment total_chunks was a positive int
    assert len(observed_total_chunks) == 1
    assert observed_total_chunks[0] is not None
    assert observed_total_chunks[0] >= 1
```

- [ ] **Step 3: Run, verify all 3 new tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_storage.py tests/test_ingest.py -v -k "update_pending_episode or process_writes_total_chunks"
```

Expected: 3 FAIL. Two with `AttributeError: module 'storage' has no attribute 'update_pending_episode'`; one with `assert observed[0] is not None`.

- [ ] **Step 4: Add `update_pending_episode` to `/Users/noah/Desktop/feed-me/storage.py`**

Add this function after `write_pending_episode` (or alongside the other pending-related helpers):

```python
def update_pending_episode(
    data_dir: Path, secret: str, slug: str, *,
    total_chunks: int | None = None,
) -> None:
    """Update fields on an existing pending episode record.

    Reads the JSON, updates the specified fields, writes back. Existing
    fields preserved. No-op if the record doesn't exist (caller can fire-and-forget).
    """
    path = data_dir / secret / f"{slug}.json"
    if not path.exists():
        return
    record = json.loads(path.read_text())
    if total_chunks is not None:
        record["total_chunks"] = total_chunks
    path.write_text(json.dumps(record))
```

- [ ] **Step 5: Update `process` in `/Users/noah/Desktop/feed-me/ingest.py` to chunk + write total_chunks before synthesize**

Find the existing `process` function and REPLACE it with this version. Only changes vs. the current v1.8 version: the `chunk_text(body, TTS_CHAR_LIMIT)` line and the `storage.update_pending_episode(...)` line, both inserted right after the cap check.

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
```

- [ ] **Step 6: Run the full suite, verify all tests pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: 97 tests pass (was 94, plus 3 new).

- [ ] **Step 7: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add storage.py ingest.py tests/test_storage.py tests/test_ingest.py && git commit -m "feat(storage): update_pending_episode; ingest writes total_chunks after chunking

- New storage.update_pending_episode(slug, *, total_chunks=N) preserves
  other fields on a pending record. No-op if the slug doesn't exist.
- ingest.process now calls chunk_text + update_pending_episode after
  fetch_article, before synthesize. The polling endpoint can pick up
  total_chunks during the pending window so the settings page can
  render a smooth % progress.
- chunk_text runs twice per ingest (here + inside synthesize). Pure
  Python on ~50k chars takes <10ms; not worth refactoring synthesize's
  signature to deduplicate."
```

---

## Task 2: Template `data-*` attrs + JS ticker

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/templates/_episodes_section.html`
- Modify: `/Users/noah/Desktop/feed-me/templates/settings.html`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Append a failing app test to `/Users/noah/Desktop/feed-me/tests/test_app.py`**

```python
def test_settings_pending_row_has_data_attributes(client, tmp_path):
    """Pending rows must carry data-ts and data-chunks for the JS ticker."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://example.com/x", title="Loading",
    )
    storage.update_pending_episode(tmp_path, secret, slug, total_chunks=7)

    response = client.get(f"/u/{secret}")
    # JS ticker reads these to compute % live
    assert 'data-ts="' in response.text
    assert 'data-chunks="7"' in response.text
    # The pending-progress span exists (initially empty; JS fills it)
    assert 'pending-progress' in response.text
```

- [ ] **Step 2: Run, verify it FAILS**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py::test_settings_pending_row_has_data_attributes -v
```

Expected: FAIL — none of these substrings exist yet.

- [ ] **Step 3: Update `/Users/noah/Desktop/feed-me/templates/_episodes_section.html`**

Find the Pending branch of the status cell, which currently reads:

```html
{% elif ep.status == "pending" %}
  <span class="status-chip pending">Pending</span>
```

Replace with:

```html
{% elif ep.status == "pending" %}
  <span class="status-chip pending">Pending</span>
  <span class="pending-progress"
        data-ts="{{ ep.ts }}"
        data-chunks="{{ ep.total_chunks or 0 }}"></span>
```

The empty `<span>` is filled in by JS within ~1s. When `total_chunks` isn't yet set (still in fetch_article window), the JS leaves it empty.

- [ ] **Step 4: Add CSS for `.pending-progress` to `/Users/noah/Desktop/feed-me/templates/settings.html`**

Find the closing `</style>` tag in the head. Just before it, append:

```css
    /* v2.0: pending progress percent under the Pending chip */
    .status-chip.pending + .pending-progress {
      display: block;
      font-size: 10px;
      color: #6a6a6a;
      margin-top: 3px;
      font-variant-numeric: tabular-nums;
    }
```

- [ ] **Step 5: Add the JS ticker block to `/Users/noah/Desktop/feed-me/templates/settings.html`**

Find the existing polling-script block at the bottom of the file (the IIFE that calls `refresh()` every 3s). Append this NEW `<script>` block IMMEDIATELY AFTER it:

```html
  <script>
    // v2.0: tick a smooth % under each Pending chip every 1s.
    (function () {
      var SECONDS_PER_CHUNK = 5;
      var MIN_EXPECTED_SECONDS = 30;
      var MAX_DISPLAY_PERCENT = 95;

      function tick() {
        var nowTs = Math.floor(Date.now() / 1000);
        var nodes = document.querySelectorAll(".pending-progress");
        for (var i = 0; i < nodes.length; i++) {
          var el = nodes[i];
          var startTs = parseInt(el.dataset.ts, 10);
          var totalChunks = parseInt(el.dataset.chunks, 10);
          if (!startTs) continue;
          // Hide percent until total_chunks is real. Without this, the
          // fallback expected-time estimate would later jump DOWN when
          // total_chunks arrives via polling, violating "never backwards".
          if (!totalChunks || totalChunks < 1) {
            el.textContent = "";
            continue;
          }
          var elapsed = nowTs - startTs;
          var expected = Math.max(MIN_EXPECTED_SECONDS, totalChunks * SECONDS_PER_CHUNK);
          var pct = Math.min(MAX_DISPLAY_PERCENT, Math.max(0, Math.round((elapsed / expected) * 100)));
          el.textContent = pct + "%";
        }
      }
      tick();
      setInterval(tick, 1000);
    })();
  </script>
```

- [ ] **Step 6: Run the full suite, verify all tests pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: 98 tests pass (was 97, plus 1 new).

- [ ] **Step 7: Local sanity check (optional)**

```bash
cd /Users/noah/Desktop/feed-me && uv run uvicorn app:app --port 8000
```

In another shell:

```bash
SECRET=$(curl -s -X POST http://localhost:8000/create -o /dev/null -w "%{redirect_url}" | sed 's|.*/u/||')
echo "open http://localhost:8000/u/$SECRET"
```

Visit the URL. You'll only see the Welcome episode (Ready). To test the % indicator, manually inject a pending episode in another shell:

```bash
cd /Users/noah/Desktop/feed-me && uv run python -c "
import storage, time
from pathlib import Path
# Use the tmp_path-like real data dir — won't survive but enough for visual check
data_dir = Path('/data') if Path('/data').exists() else Path.cwd() / '_localdata'
data_dir.mkdir(exist_ok=True)
"
```

Actually this is awkward locally; skip and verify on prod in Task 3.

Kill the local server with Ctrl+C.

- [ ] **Step 8: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add templates/_episodes_section.html templates/settings.html tests/test_app.py && git commit -m "feat(app): smooth percent ticker on Pending chips

- _episodes_section.html: pending status cell now includes a <span
  class='pending-progress'> with data-ts and data-chunks attributes
  read by the new JS ticker.
- settings.html: 1Hz JS ticker that recomputes percent from elapsed
  time and total_chunks. Caps at 95% (so 'Ready' is the only signal
  for completion). Hides percent entirely when total_chunks isn't yet
  set (still in fetch_article window) to avoid showing a percent that
  would later jump DOWN.
- Existing 3s episodes_partial polling provides fresh data-attrs as
  new pending records arrive."
```

---

## Task 3: Deploy v2.0 + tag

**Files:** none (deploy + CHANGELOG + tag)

- [ ] **Step 1: Deploy**

```bash
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

- [ ] **Step 2: Smoke test on prod**

```bash
curl -s "https://feed-me.xyz/u/GZ3wWyxsNZSraasSwlfYO_OhPrFI3uk9v5pYl-886AA/episodes_partial" | grep -E "(pending-progress|data-ts|data-chunks)" | head -3
```

If you have a recently-shared pending episode, this should show the data-attrs. If no pending, it'll show nothing — that's OK; we'll verify via real share.

- [ ] **Step 3: iPhone share test**

On your iPhone, share any article via the Feed Me Shortcut. Within ~3s the Pending row should appear. Watch the percent ticker:

- For the first ~5-10 seconds (during `fetch_article`), the row shows just "Pending" with no %.
- After fetch completes, the % should start appearing (e.g., "Pending · 12%") and tick up every second.
- Percent should never decrease.
- When the row flips to Ready, the chip changes and the % goes away.

If percent doesn't appear at all, or appears immediately at high value, something's off — tell me before tagging.

- [ ] **Step 4: Update CHANGELOG and tag v2.0**

Insert this entry at the top of `/Users/noah/Desktop/feed-me/CHANGELOG.md`:

```markdown
## v2.0 — 2026-05-29

Pending progress indicator:

- Pending rows now show a smooth percent (e.g., "Pending · 42%") that ticks up every second so friends can see ingest is alive.
- Percent is computed client-side from elapsed time and `total_chunks` (written to the pending record after `chunk_text` runs). Caps at 95% until the row actually flips to Ready, never goes backwards.
- New `storage.update_pending_episode(slug, *, total_chunks=N)` helper updates an existing pending record without losing other fields.
- Spec: `docs/superpowers/specs/2026-05-29-pending-progress-indicator.html`
```

Then:

```bash
cd /Users/noah/Desktop/feed-me && git add CHANGELOG.md && git commit -m "release: v2.0 pending progress indicator" && git tag v2.0
```

---

## Self-Review

### Spec coverage

| Spec section | Implementing task |
|---|---|
| §2 Backend writes total_chunks after chunking | Task 1 step 5 |
| §2 list_episodes exposes total_chunks | Implicit — list_episodes already returns the dict from JSON; no code change needed |
| §2 Template adds data-ts/data-chunks | Task 2 step 3 |
| §2 JS ticker at 1Hz | Task 2 step 5 |
| §3 Percent calculation (formula + table) | Task 2 step 5 (formula matches spec verbatim) |
| §4 storage.update_pending_episode | Task 1 step 4 |
| §4 chunk_text runs twice (acceptable) | Task 1 step 5 (in-line comment) |
| §4 "Hide percent until total_chunks is real" fix | Task 2 step 5 (in-line comment explains why) |
| §5 Storage tests (2 new) | Task 1 step 1 |
| §5 Ingest test (synthesize observer pattern) | Task 1 step 2 |
| §5 App test for data attrs | Task 2 step 1 |
| §8 Acceptance: never backwards, caps at 95%, ~46% at 30s | Task 2 step 5 (JS) + Task 3 step 3 (iPhone verify) |

All spec sections covered. Out-of-scope items (chunks_done tracking, separate ETA number, real-time sockets) correctly absent from the plan.

### Placeholder scan

Scanned for "TBD", "TODO", "fill in", "appropriate error handling", "similar to Task N". None found. Every code block is complete. Step 7 of Task 2 (local sanity check) is honestly labeled optional — not a placeholder, just a hand-off to the prod verification in Task 3.

### Type consistency

- `update_pending_episode(data_dir, secret, slug, *, total_chunks: int | None = None)` — consistent between definition (Task 1 step 4), call site in process (Task 1 step 5), and test calls (Tasks 1 step 1, Task 2 step 1).
- `data-ts` / `data-chunks` attribute names consistent between template (Task 2 step 3), CSS selector (Task 2 step 4), JS reader (Task 2 step 5), and app test assertion (Task 2 step 1).
- `.pending-progress` class consistent between template, CSS, JS selector, and test assertion.
- `total_chunks` JSON field name consistent across storage helper, ingest write, and template read.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-29-pending-progress-indicator.md`.

Three tasks. ~25 minutes of focused subagent work plus an iPhone share to verify the % ticks correctly on prod.
