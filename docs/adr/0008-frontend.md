# ADR 0008: Frontend (Phase 7)
- Status: accepted

## Decisions
1. **React + TypeScript + Vite, no UI kit, no chart library.** The two light-curve plots are canvas
   (thousands of points, hover, DPR-aware); the evidence strip, readouts and provenance graph are
   plain SVG/DOM. The bundle is ~77 kB gzipped. Plotly/shadcn from the blueprint were deferred: nothing
   built so far needs them, and a generic kit would work against the identity below.
2. **No combined score, in the UI as in the schema.** Readouts are separate (signal, classifier with its
   90% set, anomaly percentile with its reference population, vetting, data quality, catalog status).
   Evidence tallies per direction are shown side by side and labelled as not summed.
3. **Evidence strip as the signature view.** One lane per epistemic channel; supports above the line,
   contradicts below. Direction is encoded by shape (circle, diamond, bar, ring) as well as colour.
4. **Progress is the recorder.** One lane per phase, driven by the ordered job-event log. SSE runs over
   `fetch` (EventSource cannot send `Authorization`), resumes from the last sequence number on a drop,
   and reports "lost" after repeated failures instead of hanging.
5. **Honest wording.** Triage titles come from a fixed map for the closed enum and never say
   "discovery" (tested). Unknown is shown as unknown (a failed catalog lookup is not "no entry").
6. **Demo mode is a first-class `AkashApi` implementation**, deterministic and labelled everywhere.
   Arbitrary queries are shown as "Demo target: ..." so a real star name is never attached to fake data.
7. **API key in `sessionStorage` only**, never `localStorage`.
8. **Fold epoch is estimated in the browser** because the API reports period/depth/duration but no epoch.
   The page says so. Adding `t0` to `TransitSummary` is the right fix and is a Phase 6 follow-up.

## Known limits
- Never run against the real API in this environment (no network, torch, or server): the live path is
  tested against a local HTTP server (auth, error envelope, Retry-After, chunk-split SSE frames) only.
- No browser test suite yet beyond manual Chromium screenshots; no automated accessibility audit.
- Light curve downsampling is requested at 4,000 points; very large objects are not paged.
