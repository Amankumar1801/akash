# ADR 0016: Deep-space observatory UI redesign

Status: accepted

Presentation layer only. No API, schema, scientific or routing change; every route, form, filter,
button and the demo/live and red-lamp controls behave as before.

- Design tokens (midnight navy, amber, cyan), Newsreader display, Inter body, IBM Plex Mono metadata.
- New AKASH mark (orbit ring, vertical axis, stellar glint) as an SVG component and favicon.
- Left sidebar shell (a scrolling top rail below 900 px), route settle transition, branded loader.
- Space background: seeded stars (never reshuffled), a few unsynchronised twinkles, tiny pointer
  parallax. Off for touch and `prefers-reduced-motion`; capped at ~30 fps; paused when hidden;
  never takes pointer events.
- Synthetic-case thumbnails and the hero orb are decorative and encode nothing.

Verified: tsc, 80 vitest tests, vite build, screenshots of all routes at 1440 and 390 px with no
console errors or horizontal overflow, and key flows with reduced motion. Not verified: real
browsers other than Chromium, screen readers, live-API mode visuals.
