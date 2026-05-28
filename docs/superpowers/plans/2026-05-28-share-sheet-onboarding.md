# Share Sheet Onboarding (v1.9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Share section on the settings page so friends can actually find Feed Me in iOS's share sheet on first try, and pin it to the top for one-tap future shares.

**Architecture:** Two tasks — (1) update `templates/settings.html` with the corrected 4-step Share flow, new Pin tip callout, and CSS share-sheet illustration, plus test updates; (2) deploy + tag v1.9.

**Tech Stack:** Pure template change. No backend, no new routes, no new deps. Spec: `docs/superpowers/specs/2026-05-28-share-sheet-onboarding.html`.

---

## File Structure

```
feed-me/
  templates/settings.html       # +1 step in Share section, +pin tip, +CSS illo + CSS
  tests/test_app.py             # +2 substring assertions on settings render
```

---

## Task 1: Update `templates/settings.html` + tests

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/templates/settings.html`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Update `test_settings_renders_for_known_user` in `/Users/noah/Desktop/feed-me/tests/test_app.py`**

Find the function and append two new assertions before the final closing line. Final form:

```python
def test_settings_renders_for_known_user(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}")
    assert response.status_code == 200
    # v1.3 structure: three-phase layout
    assert "Set up" in response.text
    assert "Install Shortcut" in response.text
    assert "Add to Apple Podcasts" in response.text
    assert "Copy feed URL" in response.text
    assert "Share an article" in response.text
    assert "Feed Me" in response.text
    # Episode table headers
    assert "Recent episodes" in response.text
    # Settings drawer
    assert "Settings" in response.text
    # Ingest URL still appears in the page (for the auto-copy JS)
    assert f"/u/{secret}/ingest" in response.text
    # v1.5: welcome episode pre-seeded on /create
    assert "Welcome to Feed Me" in response.text
    # v1.9: revised share sheet onboarding
    assert "More" in response.text  # the "Tap More ▼" instruction
    assert "Pin Feed Me" in response.text  # the new tip callout
```

- [ ] **Step 2: Run the test, verify the new assertions FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py::test_settings_renders_for_known_user -v
```

Expected: FAIL with one of the new substring assertions ("More" might pass accidentally if it appears elsewhere; "Pin Feed Me" will definitely fail).

- [ ] **Step 3: Update `/Users/noah/Desktop/feed-me/templates/settings.html` — Share section**

Find the existing Share section, which currently has the heading + 3 step-rows. Replace the entire Share block (from `<h2>Share an article · do this anytime</h2>` through the last `</div>` of step 3) with this updated version:

```html
  <h2>Share an article · do this anytime</h2>
  <p class="phase-note">In Safari (or Mail, Reader, anywhere with a Share button):</p>

  <div class="step-row">
    <div class="step-num">1</div>
    <div class="step-body">
      <div class="title">
        Tap <svg class="ios-share"><use href="#ios-share"/></svg> at the bottom of the screen
      </div>
      <div class="desc">That's the iOS Share button.</div>
    </div>
  </div>

  <div class="step-row">
    <div class="step-num">2</div>
    <div class="step-body">
      <div class="title">Tap <kbd>More ▼</kbd> at the bottom of the share sheet</div>
      <div class="desc">iOS hides Shortcuts behind this. Tapping it reveals the full list of actions.</div>
      <div class="share-sheet-illo" aria-hidden="true">
        <div class="ssi-row apps">
          <span class="ssi-pill">AirDrop</span>
          <span class="ssi-pill">Messages</span>
          <span class="ssi-pill">Mail</span>
          <span class="ssi-pill">…</span>
        </div>
        <div class="ssi-row action">Copy</div>
        <div class="ssi-row action">Add to Reading List</div>
        <div class="ssi-row action">Find on Page</div>
        <div class="ssi-row action ssi-more">More ▼ <span class="ssi-arrow">← tap here</span></div>
      </div>
    </div>
  </div>

  <div class="step-row">
    <div class="step-num">3</div>
    <div class="step-body">
      <div class="title">Scroll to the bottom and tap <kbd>Feed Me</kbd></div>
      <div class="desc">Shortcuts are listed alphabetically at the end of the actions. You'll get a "Sent ✓" notification.</div>
    </div>
  </div>

  <div class="step-row">
    <div class="step-num">4</div>
    <div class="step-body">
      <div class="title">Wait ~60 seconds</div>
      <div class="desc">The article appears as a new episode in your podcast app. Pull-to-refresh if it's slow.</div>
    </div>
  </div>

  <div class="pin-tip">
    <div class="pin-tip-title">💡 Pin Feed Me for one-tap sharing <span class="pin-tip-sub">(recommended, one-time)</span></div>
    <ol>
      <li>Open the share sheet on any article (Share → More)</li>
      <li>Scroll to the bottom and tap <strong>Edit Actions</strong> (or <strong>Edit Suggestions</strong> on newer iOS)</li>
      <li>Find Feed Me in the list, tap the green <strong>+</strong> next to it</li>
      <li>Tap <strong>Done</strong>. Feed Me is now at the top of your share sheet — one tap from any article forever after.</li>
    </ol>
  </div>
```

- [ ] **Step 4: Add CSS for the illustration + pin tip**

In the same `templates/settings.html` file, find the closing `</style>` tag. Just before it, add these new rules:

```css
    /* v1.9: Share-sheet illustration */
    .share-sheet-illo {
      margin: 10px 0 4px;
      background: #f5f5f7;
      border: 1px solid #e5e5ea;
      border-radius: 12px;
      padding: 8px;
      font-family: -apple-system, sans-serif;
      font-size: 11px;
    }
    .share-sheet-illo .ssi-row {
      padding: 6px 8px;
    }
    .share-sheet-illo .ssi-row + .ssi-row {
      border-top: 1px solid #e5e5ea;
    }
    .share-sheet-illo .ssi-row.apps {
      display: flex; gap: 6px; flex-wrap: wrap;
      padding-bottom: 8px;
    }
    .share-sheet-illo .ssi-pill {
      display: inline-block; padding: 2px 8px;
      background: #fff; border: 1px solid #d0d0d5; border-radius: 999px;
      color: #3a3a3a;
    }
    .share-sheet-illo .ssi-row.action { color: #1a1a1a; }
    .share-sheet-illo .ssi-row.ssi-more {
      font-weight: 700; color: #007AFF;
      display: flex; align-items: center; gap: 8px;
    }
    .share-sheet-illo .ssi-arrow {
      font-size: 10px; color: #b04a00; font-weight: 600;
    }

    /* v1.9: Pin Feed Me tip callout */
    .pin-tip {
      background: #FFF8DC;
      border-left: 3px solid #b04a00;
      padding: 14px 16px;
      margin: 20px 0 0;
      border-radius: 3px;
      font-family: -apple-system, sans-serif;
    }
    .pin-tip-title {
      font-size: 13px; font-weight: 600;
      color: #0a0a0a; margin-bottom: 6px;
    }
    .pin-tip-sub {
      font-weight: 400; color: #6a6a6a; font-size: 11px;
    }
    .pin-tip ol {
      font-size: 12px; color: #4a4a4a;
      padding-left: 18px; margin: 4px 0 0;
      line-height: 1.5;
    }
    .pin-tip ol li { margin: 4px 0; }
    .pin-tip strong { color: #0a0a0a; }
```

- [ ] **Step 5: Run all tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: all 94 tests pass (existing + the 2 new substring assertions on the renders test).

- [ ] **Step 6: Local sanity check (optional, recommended)**

```bash
cd /Users/noah/Desktop/feed-me && uv run uvicorn app:app --port 8000
```

In another shell:

```bash
SECRET=$(curl -s -X POST http://localhost:8000/create -o /dev/null -w "%{redirect_url}" | sed 's|.*/u/||')
echo "open http://localhost:8000/u/$SECRET"
```

Visit the URL. Confirm visually:
- Share section now has 4 numbered step-rows (1–4)
- Step 2 includes the small CSS-rendered share-sheet illustration with "More ▼" highlighted in blue
- A cream "Pin Feed Me" tip box appears after the 4 steps, before "Recent episodes"

Kill the local server with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add templates/settings.html tests/test_app.py && git commit -m "feat(app): share-sheet onboarding — More step, pin tip, illustration

Verified iOS flow on 2026-05-28: Shortcuts are hidden behind a 'More ▼'
button in the share sheet, then alphabetical at the bottom of the
actions list. The previous Share section skipped the More step entirely,
which meant friends following the instructions wouldn't find Feed Me
at all.

- Step 2 is now 'Tap More ▼' (was 'Scroll to Feed Me')
- Step 3 is the new 'Scroll to bottom and tap Feed Me' (was Step 2)
- Step 4 is 'Wait ~60s' (was Step 3)
- Adds an inline CSS-rendered illustration of the share sheet showing
  where More ▼ sits
- Adds a 'Pin Feed Me' tip callout (cream + accent-orange border) with
  4 steps for moving Feed Me to the top via Edit Actions/Suggestions"
```

---

## Task 2: Deploy v1.9 + tag

**Files:** none (deploy + CHANGELOG + tag)

- [ ] **Step 1: Deploy**

```bash
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

- [ ] **Step 2: Smoke test live page**

```bash
curl -s https://feed-me.xyz/u/GZ3wWyxsNZSraasSwlfYO_OhPrFI3uk9v5pYl-886AA | grep -oE "(More ▼|Pin Feed Me|Edit Actions|Tap More)" | sort -u
```

Expected: at least "More ▼" and "Pin Feed Me" appear.

- [ ] **Step 3: iPhone visual check**

On your iPhone, visit your settings page in Safari. Confirm:
- Share section reads as 4 steps (not 3)
- The little share-sheet illustration appears below Step 2's description
- A cream-colored "Pin Feed Me" box appears after the 4 steps
- Layout doesn't break at 390px width

Optionally, try the pin flow yourself: tap Share on any article, then More ▼, scroll to bottom, tap Edit Actions/Suggestions, pin Feed Me. Confirm the instructions match what you see.

- [ ] **Step 4: Update CHANGELOG and tag v1.9**

Insert this at the top of `/Users/noah/Desktop/feed-me/CHANGELOG.md`:

```markdown
## v1.9 — 2026-05-28

Share-sheet onboarding:

- Share section now correctly explains the iOS share-sheet flow: tap Share → tap **More ▼** → scroll to bottom → tap Feed Me. Previous instructions skipped the "More" step entirely, which meant friends following the page couldn't find Feed Me at all.
- New "💡 Pin Feed Me for one-tap sharing" tip callout: 4-step instructions for moving Feed Me to the top of the share sheet via Edit Actions / Edit Suggestions. Future shares become one tap.
- Small inline CSS-rendered illustration of the share sheet showing where More ▼ sits.
- Spec: `docs/superpowers/specs/2026-05-28-share-sheet-onboarding.html`
```

Then:

```bash
cd /Users/noah/Desktop/feed-me && git add CHANGELOG.md && git commit -m "release: v1.9 share sheet onboarding" && git tag v1.9
```

---

## Self-Review

### Spec coverage

| Spec section | Implementing task |
|---|---|
| §3 Revised 4-step Share flow with More ▼ | Task 1 step 3 |
| §4 Pin tip callout (cream + accent border + 4 sub-steps) | Task 1 steps 3, 4 |
| §5 Inline CSS-rendered illustration | Task 1 steps 3, 4 |
| §6 Files modified list | Tasks 1 (settings.html + test_app.py) |
| §7 Test substring assertions for "More" and "Pin Feed Me" | Task 1 step 1 |
| §10 Acceptance: 4 steps, tip callout, illustration, tests pass, deployed | All tasks |

All sections covered. Out-of-scope (screenshots, video, iOS-version detection) correctly absent.

### Placeholder scan

Scanned for "TBD", "TODO", "fill in", "appropriate error handling". None found. All code blocks (HTML and CSS) are complete. The new template section is the full final markup.

### Type consistency

- New CSS classes (`pin-tip`, `pin-tip-title`, `pin-tip-sub`, `share-sheet-illo`, `ssi-*`) are referenced consistently between the CSS and the markup.
- The existing `step-row`, `step-num`, `step-body`, `title`, `desc` classes are reused for the new Step 4 without modification.
- `kbd` styling already exists in settings.html from v1.6; the new `<kbd>More ▼</kbd>` uses it.
- `ios-share` SVG symbol from v1.5 is reused unchanged for Step 1.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-share-sheet-onboarding.md`.

Two tasks. ~15 minutes of focused subagent work plus an iPhone visual check.
