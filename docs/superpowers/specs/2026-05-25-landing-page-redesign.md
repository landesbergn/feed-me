# Feed Me — Landing Page Redesign (v1.1)

**Date:** 2026-05-25
**Status:** Spec
**Predecessor:** [v1 design](2026-05-21-feed-me-design.html) shipped at commit `4aa4380` (tag `v1.0`).

## Why

v1 launched with a functional but unfussy landing page. Now the user wants to share `feed-me-noah-willow-grove-8052.fly.dev` with friends and have them self-serve their own feed without help. The current page reads as a placeholder; it doesn't sell the product or make the value obvious enough to convert a casual visitor.

This spec covers **only the landing page**. The Shortcut wiring for friends (so a friend's `Install Shortcut` button works end-to-end) is a separate, related work item — called out under "Known follow-ups" but not part of this spec.

## What we're building

A redesigned `templates/landing.html` that:

1. Sells the product in one screen
2. Names the differentiator (it's *yours*, it's *private*) without crowding
3. Shows the three-step setup as a clear sequence so a friend knows what they're signing up for
4. Stays mobile-first (the friend almost certainly opens the link on their phone)

No backend changes. No new routes. No new dependencies.

## Visual direction

**Vibe:** Minimal — Linear/Vercel aesthetic. White background, near-black text, system sans (Inter / -apple-system stack), one accent (the black button itself). Plenty of air. No images, no audio sample, no illustrations.

**Layout (locked via visual companion):**

```
┌─────────────────────────────────────────────┐
│ Feed Me                                     │  ← brand mark, 10px uppercase, top-left
│                                             │
│ Your articles, read to you in              │  ← h1, 22-28px, weight 600, tracking -0.025em
│ your own private podcast feed.              │     "your own private" gets a 2px underline
│                                             │     "podcast feed." nbsp'd so "feed." can't orphan
│                                             │     text-wrap: balance for even line distribution
│ Share an article, play it later.            │  ← subhead, 13-14px, neutral gray
│                                             │
│ [ Get my feed → ]                           │  ← black pill button, posts to /create
│                                             │
│ ───────────────────────────────────         │  ← thin top border on the steps block
│                                             │
│ ① ─── Create your feed                      │  ← numbered circles (22px, 1.5px border)
│ │     A private URL only you know.          │     connected by a 2px hairline timeline
│ │     Bookmark it.                          │
│ │                                           │
│ ② ─── Install the Shortcut                  │  ← bold 13px title, 11px gray description
│ │     One tap. Lives in your iOS            │
│ │     share sheet.                          │
│ │                                           │
│ ③     Subscribe in any podcast app          │  ← last step: no trailing line
│       Apple Podcasts, Overcast, Pocket      │
│       Casts — standard RSS.                 │
│                                             │
└─────────────────────────────────────────────┘
```

The whole page is one column. On mobile, the column is the viewport width minus padding. On wider screens, content stays in a centered ~480px column — same as v1.

### Copy (placeholder — fixed later)

| Slot | Text |
|---|---|
| Brand | `Feed Me` (uppercase, tracked) |
| h1 | `Your articles, read to you in your own private podcast feed.` |
| h1 emphasis | `your own private` gets a 2px solid black underline |
| Subhead | `Share an article, play it later.` |
| Button | `Get my feed →` |
| Step 1 title | `Create your feed` |
| Step 1 desc | `A private URL only you know. Bookmark it.` |
| Step 2 title | `Install the Shortcut` |
| Step 2 desc | `One tap. Lives in your iOS share sheet.` |
| Step 3 title | `Subscribe in any podcast app` |
| Step 3 desc | `Apple Podcasts, Overcast, Pocket Casts — standard RSS.` |

Copy may be tweaked before or after implementation. The spec governs structure and visual treatment, not the final words.

## Implementation notes

**One file changes:** `templates/landing.html`.

**No CSS extraction:** keep styles in a `<style>` block inside the template, matching the existing pattern in `templates/landing.html` and `templates/settings.html`. No new CSS file.

**Responsive:** mobile-first. Use a single column with `max-width: 480px; margin: 60px auto` (same envelope as v1). On screens narrower than ~520px, padding stays at `0 24px`.

**Type stack:** `-apple-system, "Inter", "Helvetica Neue", system-ui, sans-serif`. No webfont loading.

**Color palette:**
- Text primary: `#0a0a0a`
- Text secondary: `#6a6a6a`
- Text tertiary: `#999`
- Border / divider: `#eaeaea`
- Background: `#fff`
- Button: `#0a0a0a` background, `#fff` text

**Step timeline:** 22px circles with `1.5px solid #0a0a0a` border, transparent inside, number centered. Vertical 2px hairline at `#eaeaea` connects the centers of consecutive circles. Last step has no trailing line.

**Text decoration:** `text-wrap: balance` on the h1; `&nbsp;` between `podcast` and `feed.` to prevent the orphan; a `<span>` with `border-bottom: 2px solid #0a0a0a` wraps `your own private`.

**Existing form-post behavior is preserved:** the button stays inside a `<form action="/create" method="post">` so the POST → 303 redirect to `/u/<secret>` flow still works exactly as before.

## Testing

The existing `test_landing_page_renders(client)` in `tests/test_app.py` asserts:
- 200 response on GET /
- `"Get my feed"` appears in the response
- `"feed-me"` appears case-insensitively

This redesign preserves all three. Update the test to also assert:
- `"private"` appears in the response (regression guard for the privacy emphasis being on the page)
- `"Create your feed"` appears (regression guard for step 1 title being present)

The visual treatment itself is verified by eye — there's no meaningful way to assert "the underline is 2px solid black" in a request-level test, and FastAPI's test client doesn't render CSS.

## Out of scope

- **Settings page (`templates/settings.html`)** — different surface, different problem. Touched only if accidentally regressed.
- **Sample audio player** — explicitly chosen against during brainstorm; would force baking a 500KB MP3 into the repo and a new route.
- **Webfonts** — system stack works fine for this aesthetic; loading webfonts adds page weight and licensing concerns.
- **Dark mode** — out of scope for v1.1; the minimal aesthetic reads fine on either OS preference today.
- **Hero illustration / screenshot of the share sheet** — explicitly chosen against (pure type per the vibe selection).
- **Analytics, conversion tracking, or A/B testing infra** — premature for a tool a handful of friends might use.

## Known follow-ups (separate work items)

These are required for the *friend journey* to be truly end-to-end usable but are independent from the landing page redesign:

1. **Wire the iCloud Shortcut share link**: re-author the Shortcut using Apple's "Import Questions" feature so installers are prompted for their own ingest URL during install; set `SHORTCUT_ICLOUD_URL` on Fly. Without this, the "Install Shortcut" button on every settings page points to a placeholder.

2. **Improve the bookmark-the-URL onboarding moment**: today the URL-as-account warning is a yellow box on the settings page, easy to miss. Consider an explicit "Bookmark this page" confirmation step (one screen between `POST /create` and the settings view) that interrupts the redirect flow until the user acknowledges. Out of scope here; raised because the landing page does mention "bookmark the URL" and the actual bookmarking experience should match.

Both should get their own spec → plan cycle.

## Acceptance criteria

- `templates/landing.html` rewritten with the layout and styles above
- All existing landing-page tests still pass
- New regression assertions for `"private"` and `"Create your feed"` added
- Deployed to Fly; `https://feed-me-noah-willow-grove-8052.fly.dev/` shows the redesigned page
- On an iPhone Safari render in portrait (iPhone 14 / 15-class, 6.1" / 390×844pt with default Safari chrome), the hero, button, and all three steps are visible without scrolling
