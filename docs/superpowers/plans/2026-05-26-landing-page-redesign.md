# Landing Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `templates/landing.html` with the v1.1 design — minimal Linear-style hero, privacy-first headline, timeline 3-step explainer — and ship it to `https://feed-me.xyz`.

**Architecture:** Pure template change. One file rewritten (`templates/landing.html`). One test extended (`tests/test_app.py`). No backend changes, no new routes, no new dependencies. Form-post behavior to `/create` preserved exactly.

**Tech Stack:** Jinja2 template (already wired through `templates = Jinja2Templates(directory="templates")` in `app.py`), pytest, system-font CSS (no webfonts), Fly.io for deploy. Spec: `docs/superpowers/specs/2026-05-25-landing-page-redesign.html`.

---

## File Structure

```
feed-me/
  templates/
    landing.html          # REWRITTEN
  tests/
    test_app.py           # +2 assertions in test_landing_page_renders
```

That's it. No new files. No backend touched.

---

## Task 1: Extend the landing test with new regression guards

We need two new assertions in `test_landing_page_renders` so the privacy emphasis and the step-1 title can't silently regress later.

**Files:**
- Modify: `tests/test_app.py` — extend `test_landing_page_renders`

- [ ] **Step 1: Locate the existing test**

Open `tests/test_app.py` and find `test_landing_page_renders`. It currently looks like:

```python
def test_landing_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Get my feed" in response.text
    assert "feed-me" in response.text.lower()
```

- [ ] **Step 2: Replace with the extended version (TDD red)**

Replace the function with:

```python
def test_landing_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Get my feed" in response.text
    assert "feed-me" in response.text.lower()
    # v1.1 regression guards
    assert "private" in response.text.lower()
    assert "Create your feed" in response.text
```

- [ ] **Step 3: Run the test, verify the two new assertions FAIL**

Run from the project root:

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py::test_landing_page_renders -v
```

Expected: FAIL on `assert "private" in response.text.lower()` (the current template doesn't contain the word "private" anywhere). This is the TDD red phase — proves the test guards real new behavior.

- [ ] **Step 4: Commit (red phase)**

```bash
git add tests/test_app.py
git commit -m "test(app): add regression guards for v1.1 landing redesign"
```

Committing the red test is fine — Task 2 immediately makes it green, and CI between the two commits is unlikely (you're working locally on master).

---

## Task 2: Rewrite the landing template

Replace `templates/landing.html` with the new design. Single-column, mobile-first, system fonts, timeline steps. The full file is below.

**Files:**
- Modify: `templates/landing.html` — full rewrite

- [ ] **Step 1: Open `templates/landing.html` and replace its entire contents with:**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>feed-me</title>
  <style>
    body {
      font-family: -apple-system, "Inter", "Helvetica Neue", system-ui, sans-serif;
      max-width: 480px;
      margin: 60px auto;
      padding: 0 24px;
      line-height: 1.5;
      color: #0a0a0a;
      background: #fff;
      -webkit-font-smoothing: antialiased;
    }
    .brand {
      font-size: 10px;
      color: #999;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-weight: 700;
      margin-bottom: 24px;
    }
    h1 {
      font-size: 28px;
      font-weight: 600;
      letter-spacing: -0.025em;
      line-height: 1.15;
      margin: 0 0 10px;
      text-wrap: balance;
    }
    h1 .key {
      border-bottom: 2px solid #0a0a0a;
      padding-bottom: 1px;
    }
    .sub {
      font-size: 14px;
      color: #6a6a6a;
      line-height: 1.4;
      margin: 0 0 18px;
    }
    button {
      display: inline-block;
      background: #0a0a0a;
      color: #fff;
      font-size: 14px;
      padding: 10px 20px;
      border: none;
      border-radius: 999px;
      font-weight: 500;
      font-family: inherit;
      cursor: pointer;
    }
    .steps {
      margin-top: 24px;
      padding-top: 20px;
      border-top: 1px solid #eee;
    }
    .step {
      display: grid;
      grid-template-columns: 24px 1fr;
      gap: 14px;
      position: relative;
      padding-bottom: 14px;
    }
    .step:not(:last-child)::before {
      content: '';
      position: absolute;
      left: 11px;
      top: 26px;
      bottom: 0;
      width: 2px;
      background: #eaeaea;
    }
    .circle {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      border: 1.5px solid #0a0a0a;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 700;
      background: #fff;
      position: relative;
      z-index: 1;
    }
    .step-title {
      font-size: 13px;
      font-weight: 600;
      color: #0a0a0a;
      line-height: 1.3;
      margin-bottom: 2px;
    }
    .step-desc {
      font-size: 11px;
      color: #888;
      line-height: 1.4;
    }
  </style>
</head>
<body>
  <div class="brand">Feed Me</div>
  <h1>Your articles, read to you in <span class="key">your own private</span>&nbsp;podcast&nbsp;feed.</h1>
  <p class="sub">Share an article, play it later.</p>
  <form action="/create" method="post">
    <button type="submit">Get my feed →</button>
  </form>
  <div class="steps">
    <div class="step">
      <div class="circle">1</div>
      <div>
        <div class="step-title">Create your feed</div>
        <div class="step-desc">A private URL only you know. Bookmark it.</div>
      </div>
    </div>
    <div class="step">
      <div class="circle">2</div>
      <div>
        <div class="step-title">Install the Shortcut</div>
        <div class="step-desc">One tap. Lives in your iOS share sheet.</div>
      </div>
    </div>
    <div class="step">
      <div class="circle">3</div>
      <div>
        <div class="step-title">Subscribe in any podcast app</div>
        <div class="step-desc">Apple Podcasts, Overcast, Pocket Casts — standard RSS.</div>
      </div>
    </div>
  </div>
</body>
</html>
```

**Notes on the template:**

- `<title>feed-me</title>` (lowercase with hyphen) preserves the existing `"feed-me" in response.text.lower()` test assertion. The brand mark on the page itself reads "Feed Me" (visible to humans).
- `&nbsp;` between `podcast` and `feed.` prevents `feed.` from orphaning onto its own line. The headline never breaks between those two words.
- `<span class="key">your own private</span>` wraps the privacy phrase so it can be underlined as one unit. `border-bottom: 2px solid #0a0a0a` gives the 2px solid black underline.
- `text-wrap: balance` on the `h1` distributes the remaining wrap evenly across lines.
- The form preserves the `POST /create` → 303 redirect behavior unchanged.
- The timeline hairline (`.step:not(:last-child)::before`) is positioned at `left: 11px` so it lands at the center of the 22px circles. `top: 26px` clears the circle, `bottom: 0` extends to the bottom of the step (which equals the top of the next circle because of grid alignment).
- `.step-title`, `.step-desc`, `.steps`, `.step`, `.circle`, `.brand`, `.sub`, `.key` are all freshly named — no collision with the existing `templates/settings.html` (which has its own style block in a separate file).

- [ ] **Step 2: Run the full test suite, verify all tests pass (TDD green)**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v
```

Expected: all tests pass, including `test_landing_page_renders` with the two new assertions. Total test count: same as before (42).

- [ ] **Step 3: Manual local sanity check**

Run the app locally to eyeball the page in a browser:

```bash
cd /Users/noah/Desktop/feed-me && uv run uvicorn app:app --port 8000
```

Open `http://localhost:8000/` in a browser. Confirm:
- Brand mark "Feed Me" reads as small uppercase in the top-left
- Headline shows on 2-3 lines depending on viewport, with a solid black underline under "your own private"
- "feed." never appears alone on its own line
- The black "Get my feed →" pill button is visible and clickable
- Three numbered circles connected by a vertical hairline
- All three step titles and descriptions are readable

If anything looks off, fix the template and re-test before committing. Kill the local server with `Ctrl+C`.

- [ ] **Step 4: Commit (green phase)**

```bash
git add templates/landing.html
git commit -m "feat(app): redesign landing page with timeline steps and privacy-first headline

- Minimal Linear-style hero with system fonts, no images, no audio sample
- Headline 'Your articles, read to you in your own private podcast feed'
  with 2px solid underline on 'your own private'
- 3-step timeline explainer (numbered circles + connecting hairline)
- Form-post to /create preserved exactly
- Spec: docs/superpowers/specs/2026-05-25-landing-page-redesign.html"
```

---

## Task 3: Deploy to Fly and smoke test on feed-me.xyz

Push the template change to production and verify it renders correctly on the live custom domain.

**Files:** none (deploy only)

- [ ] **Step 1: Deploy**

```bash
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

Expected: build completes, machine update succeeds, no errors. Takes ~1-2 minutes (`uv sync` is cached from prior layers since dependencies didn't change).

- [ ] **Step 2: Smoke test the live HTML**

```bash
curl -s https://feed-me.xyz/ | grep -E "(Get my feed|Create your feed|your own private)" | head -5
```

Expected: three matching lines — one from the button, one from the step 1 title, one from the headline.

- [ ] **Step 3: Confirm the live POST flow still works**

```bash
curl -s -X POST https://feed-me.xyz/create -i | grep -iE "^(HTTP|location)"
```

Expected: `HTTP/2 303` + `location: /u/<32+ char secret>`. Confirms the form-post unchanged.

- [ ] **Step 4: iPhone visual verification**

On your iPhone, open Safari and navigate to `https://feed-me.xyz/`. Confirm against the spec's acceptance criteria:

- Brand mark, hero, button, and all three steps are visible **without scrolling** in portrait on a 6.1" iPhone (iPhone 14 / 15-class, 390×844pt with default Safari chrome)
- Headline reads in 2-3 balanced lines; "feed." is never alone on its own line
- "your own private" is underlined with a solid 2px black line
- Tap "Get my feed →" — should redirect to your settings page (you'll need to bookmark the new account or rotate back to your existing one)

If the page overflows the viewport, the spec's acceptance criterion isn't met. Likely culprit: `h1` font-size too large or `padding-bottom` on the steps too generous. Tweak in `templates/landing.html`, re-deploy, re-check. Don't commit "good enough" — the spec is explicit about one-viewport fit.

- [ ] **Step 5: Tag and changelog**

```bash
cd /Users/noah/Desktop/feed-me && cat >> CHANGELOG.md << 'EOF'

## v1.1 — 2026-05-26

Landing page redesign:
- Minimal Linear-style hero, privacy-first headline
- 3-step timeline explainer replaces the old ordered list
- "Your articles, read to you in your own private podcast feed." headline
- New regression test guards for "private" and "Create your feed"
- Deployed to https://feed-me.xyz (custom domain wired up the same day)
EOF
git add CHANGELOG.md
git commit -m "release: v1.1 landing page redesign"
git tag v1.1
```

---

## Self-Review

### Spec coverage

| Spec section | Implementing task |
|---|---|
| §3 Visual direction (vibe, layout) | Task 2 step 1 (template HTML + CSS) |
| §4 Copy table (all 11 slots) | Task 2 step 1 (each slot in the template) |
| §5 Implementation: one file changes | Task 2 (only `templates/landing.html` modified) |
| §5 No CSS extraction | Task 2 (style block inside template) |
| §5 Responsive (480px column, mobile-first) | Task 2 (`max-width: 480px; margin: 60px auto`) |
| §5 Type stack (system fonts) | Task 2 (`font-family: -apple-system, "Inter", …`) |
| §5 Color palette | Task 2 (all hex values in style block) |
| §5 Step timeline (22px circles, 1.5px border, 2px hairline) | Task 2 |
| §5 Text decoration (text-wrap balance, nbsp, underline span) | Task 2 |
| §5 Form behavior preserved | Task 2 (`<form action="/create" method="post">`) |
| §6 Testing: existing assertions preserved + 2 new | Task 1 |
| §9 Acceptance: deployed to feed-me.xyz | Task 3 |
| §9 Acceptance: one-viewport fit on 6.1" iPhone | Task 3 step 4 |

All spec sections covered. The "out of scope" and "known follow-ups" sections of the spec are correctly not implemented (separate work).

### Placeholder scan

Scanned for "TBD", "TODO", "implement later", "fill in", "appropriate error handling", "similar to Task N". None found. The template HTML is complete and literal; the CSS is complete with explicit values; the test code is the full final version; the deploy commands are exact.

### Type consistency

There are no functions or types crossing tasks here — it's a template change. CSS class names used in Task 2 step 1 (`brand`, `key`, `sub`, `steps`, `step`, `circle`, `step-title`, `step-desc`) all match between the HTML markup and the style block. The `<title>feed-me</title>` consistently uses lowercase-with-hyphen to satisfy the test assertion added in Task 1.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-26-landing-page-redesign.md`.

This is a small, focused plan: 3 tasks, ~15 minutes of work end-to-end (most of it is `fly deploy` waiting). Either execution mode works fine.
