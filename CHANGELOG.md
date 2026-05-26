# Changelog

## v1.1 — 2026-05-26

Landing page redesign + custom domain:

- Minimal Linear-style hero, privacy-first headline (`Your articles, read to you in your own private podcast feed.`) with underlined privacy phrase
- 3-step timeline explainer (numbered circles + connecting hairline) replaces the old ordered list
- Custom domain wired up: `https://feed-me.xyz` (with `www` cert too); old fly subdomain still works
- New test regression guards for `"private"` and `"Create your feed"` on the landing
- Step-desc grey bumped to `#6a6a6a` for WCAG AA contrast
- Spec: `docs/superpowers/specs/2026-05-25-landing-page-redesign.html`

## v1.0 — 2026-05-25

Initial release. End-to-end self-serve podcast feed:

- Self-serve onboarding at `/` → `POST /create` → `/u/<secret>` settings page
- iOS Shortcut → `GET /u/<secret>/ingest?url=...` spawns daemon worker
- Readability extracts article body → OpenAI TTS (`tts-1`, configurable voice) → MP3 written to `/data/<secret>/<slug>.mp3`
- RSS 2.0 feed at `/u/<secret>/feed.xml`; MP3s served from `/u/<secret>/audio/<slug>.mp3`
- Voice picker (shimmer / alloy / nova / echo) and URL rotation on settings page
- Failure visibility: failed ingests appear inline on the settings page with the error
- Deployed to Fly.io (sjc) on a 3GB volume; ~$2-5/mo + OpenAI TTS usage

End-to-end smoke verified: share `paulgraham.com/winc.html` → episode in Apple Podcasts ~60s later.
