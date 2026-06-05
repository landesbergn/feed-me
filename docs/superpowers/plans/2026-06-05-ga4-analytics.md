# GA4 Audience Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the owner's GA4 snippet to the three user-facing pages so GA reports device, geo (city/state/country), and referrer, while guaranteeing the feed secret never reaches Google.

**Architecture:** One Jinja partial (`templates/_ga.html`) holds the snippet plus two masks: a referrer mask (any `document.referrer` whose path starts with `/u/` is reported as `<origin>/u/_`) and an optional location mask (`ga_mask_location` flag, set only by `settings.html`, reports `page_location` as `<base_url>/u/_`). Landing and share include the partial bare; settings sets the flag first. The admin page never includes it. Self-hosted SQLite analytics are untouched.

**Tech Stack:** Jinja2 partial include (context is shared by default, so an undefined `ga_mask_location` is simply falsy), GA4 gtag.js, pytest string assertions against rendered templates (TestClient never executes JS, so tests stay network-free).

**Spec:** `docs/superpowers/specs/2026-06-05-ga4-analytics.html`

**Conventions that apply here (from CLAUDE.md):**
- TDD: write the failing test first, watch it fail, then implement.
- No em-dashes in any user-facing or doc text you add (middot `·` is fine).
- The raw feed secret must never be logged or exposed; that rule is the reason the masks exist.
- The `client` pytest fixture monkeypatches `APP_BASE_URL` to `https://test.local`, so masked locations render as `https://test.local/u/_` in tests.

---

### Task 1: GA partial + landing page

**Files:**
- Create: `templates/_ga.html`
- Modify: `templates/landing.html` (head, after the viewport meta)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
def test_ga_snippet_on_landing(client):
    body = client.get("/").text
    assert "googletagmanager.com/gtag/js?id=G-MQ15LHLSBF" in body
    # referrer-masking logic ships with the snippet everywhere
    assert "page_referrer" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py::test_ga_snippet_on_landing -v`
Expected: FAIL on the first assert (snippet not in page).

- [ ] **Step 3: Create the partial**

Create `templates/_ga.html` with exactly:

```html
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-MQ15LHLSBF"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  // Never send a /u/<secret> URL to Google: mask the referrer always, and on
  // pages whose own URL contains the secret (settings sets ga_mask_location)
  // mask the reported location too.
  var gaCfg = {};
  try {
    if (document.referrer) {
      var gaRef = new URL(document.referrer);
      if (gaRef.pathname.indexOf('/u/') === 0) {
        gaCfg.page_referrer = gaRef.origin + '/u/_';
      }
    }
  } catch (e) {}
  {% if ga_mask_location %}
  gaCfg.page_location = '{{ base_url }}/u/_';
  gaCfg.page_path = '/u/_';
  {% endif %}
  gtag('config', 'G-MQ15LHLSBF', gaCfg);
</script>
```

- [ ] **Step 4: Include it on the landing page**

In `templates/landing.html`, the head starts:

```html
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
```

Add the include directly after the viewport meta line:

```html
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {% include "_ga.html" %}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_app.py::test_ga_snippet_on_landing -v`
Expected: PASS

- [ ] **Step 6: Run the full suite (regression)**

Run: `uv run pytest`
Expected: all pass. (Landing-page tests assert on copy, not scripts, so nothing else should move.)

- [ ] **Step 7: Commit**

```bash
git add templates/_ga.html templates/landing.html tests/test_app.py
git commit -m "feat: GA4 snippet partial, included on landing page"
```

---

### Task 2: Settings page, with location masking

**Files:**
- Modify: `templates/settings.html` (head, after the viewport meta)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
def test_ga_snippet_on_settings_masks_secret(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    body = client.get(f"/u/{secret}").text
    assert "googletagmanager.com/gtag/js?id=G-MQ15LHLSBF" in body
    # The page's own URL contains the secret, so GA must report /u/_ instead.
    assert "gaCfg.page_location = 'https://test.local/u/_'" in body
    assert "gaCfg.page_path = '/u/_'" in body
    assert "page_referrer" in body  # referrer mask ships here too
    # The secret legitimately appears elsewhere on the page (feed URL box), but
    # never on any GA-related line.
    ga_lines = [l for l in body.splitlines()
                if "gtag" in l or "gaCfg" in l or "googletagmanager" in l]
    assert ga_lines
    assert all(secret not in l for l in ga_lines)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py::test_ga_snippet_on_settings_masks_secret -v`
Expected: FAIL on the first assert (snippet not on settings page).

- [ ] **Step 3: Include the partial with the mask flag**

In `templates/settings.html`, the head starts:

```html
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
```

Add after the viewport meta line (the `set` must come before the include; the
settings route already passes `base_url` in its context):

```html
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {% set ga_mask_location = true %}
  {% include "_ga.html" %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_app.py::test_ga_snippet_on_settings_masks_secret -v`
Expected: PASS

- [ ] **Step 5: Run the full suite (regression)**

Run: `uv run pytest`
Expected: all pass. If `test_admin_stats_shows_feed_hash_never_the_raw_secret`
or any settings-page test fails, stop and inspect; do not weaken those tests.

- [ ] **Step 6: Commit**

```bash
git add templates/settings.html tests/test_app.py
git commit -m "feat: GA4 on settings page with page_location masked to /u/_"
```

---

### Task 3: Share page + admin exclusion guard

**Files:**
- Modify: `templates/share.html` (head, after the viewport meta)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test (plus the admin guard, which passes from the start by design)**

Append to `tests/test_app.py`:

```python
def test_ga_snippet_on_share_page(client):
    # No cookie → the "connect" state renders; the snippet ships on all states.
    body = client.get("/share?url=https://example.com/a").text
    assert "googletagmanager.com/gtag/js?id=G-MQ15LHLSBF" in body
    assert "page_referrer" in body


def test_ga_snippet_not_on_admin_stats(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    body = client.get("/admin/stats?token=right").text
    assert "googletagmanager" not in body
```

- [ ] **Step 2: Run both; verify the share test fails and the admin guard passes**

Run: `uv run pytest tests/test_app.py::test_ga_snippet_on_share_page tests/test_app.py::test_ga_snippet_not_on_admin_stats -v`
Expected: share test FAILS (snippet absent), admin test PASSES (it is a
regression guard; nothing ever adds the partial there).

- [ ] **Step 3: Include the partial on the share page**

In `templates/share.html`, the head starts:

```html
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
```

Add after the viewport meta line:

```html
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {% include "_ga.html" %}
```

- [ ] **Step 4: Run tests to verify both pass**

Run: `uv run pytest tests/test_app.py::test_ga_snippet_on_share_page tests/test_app.py::test_ga_snippet_not_on_admin_stats -v`
Expected: both PASS

- [ ] **Step 5: Run the full suite (regression)**

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add templates/share.html tests/test_app.py
git commit -m "feat: GA4 on share page; admin stats stays untracked"
```

---

### Task 4: Documentation (README, CLAUDE.md, CHANGELOG)

**Files:**
- Modify: `README.md` (the `### Analytics` section)
- Modify: `CLAUDE.md` (Gotchas list)
- Modify: `CHANGELOG.md` (new entry at top)

- [ ] **Step 1: Rewrite the README analytics section**

In `README.md`, find the `### Analytics` section (it currently opens with
"Self-hosted, privacy-preserving, no third party."). Replace the whole section
body with:

```markdown
### Analytics

Two tiers. **Operational stats are self-hosted**: events (`page_view`,
`feed_created`, `article_shared`) go to a SQLite DB at
`/data/_analytics/analytics.db` (its own subdir so the `/data/<secret>/` feed
level stays pure). Each event is attributed by a **one-way `sha256(secret)[:12]`
hash, never the raw secret**, so this store can never reveal a private feed
URL. `article_shared` events also store the article URL + title. Writes are
fire-and-forget and can never break a page render.

**Audience analytics are Google Analytics 4** (`templates/_ga.html`, included
by the landing, settings, and share pages; the admin page is not tracked):
device, browser, city/state/country, and referrer reporting in the GA UI.
Google receives the visitor's IP, user agent, and referrer, never the feed
secret: the settings page reports its location as `/u/_`, and any referrer
containing `/u/<secret>` is masked the same way before the config call fires.
```

Keep whatever follows the section (the next `###` heading) untouched.

- [ ] **Step 2: Add the CLAUDE.md gotcha**

In `CLAUDE.md`, append this bullet to the Gotchas list:

```markdown
- GA4 lives in `templates/_ga.html`. `page_location` / `page_referrer` must be
  masked on any page whose URL can contain `/u/<secret>` (settings sets
  `ga_mask_location` before the include). Never add the GA partial to a new
  secret-bearing page without the mask; the raw secret must never reach Google.
```

- [ ] **Step 3: Add the CHANGELOG entry**

At the top of `CHANGELOG.md` (directly under `# Changelog`), add:

```markdown
## v3.7 — 2026-06-05

Audience analytics via Google Analytics 4.

- The landing, settings, and share pages load GA4 (`G-MQ15LHLSBF`) through a
  shared `templates/_ga.html` partial: device, browser, city/state/country, and
  referrer reporting. The admin page is not tracked.
- The feed secret never reaches Google: the settings page reports its location
  as `/u/_`, and any `/u/<secret>` referrer is masked before the config fires.
- The self-hosted SQLite analytics and `/admin/stats` are unchanged.
```

(The `—` in the version heading matches the existing changelog headings; do not
use em-dashes in the body text.)

- [ ] **Step 4: Em-dash check on user-facing template changes**

Run: `grep -n "—" templates/_ga.html templates/landing.html templates/settings.html templates/share.html`
Expected: no output from `_ga.html` (pre-existing template content unchanged by
this work is out of scope).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md CHANGELOG.md
git commit -m "docs: README two-tier analytics, GA masking gotcha, changelog for v3.7"
```

---

### Task 5: Release (confirm with Noah before deploying)

**Files:** none (git tag + deploy)

- [ ] **Step 1: Full suite, one last time**

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 2: Tag and push (ask Noah first if executing autonomously)**

```bash
git tag v3.7
git push origin main --tags
```

- [ ] **Step 3: Deploy (this exact invocation, from CLAUDE.md)**

```bash
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

A "not listening on 0.0.0.0:8000" warning during deploy is a benign Fly timing
artifact.

- [ ] **Step 4: Verify production**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://feed-me.xyz/healthz   # expect 200
curl -s https://feed-me.xyz/ | grep -c "googletagmanager.com/gtag/js?id=G-MQ15LHLSBF"   # expect 1
```

Then confirm in the GA4 Realtime report that a visit to https://feed-me.xyz
registers, and that visiting a feed page shows `page_path` of `/u/_` (never the
real secret) in the page report.
