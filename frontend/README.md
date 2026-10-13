# Akash frontend

React + TypeScript + Vite. Talks to the Phase 6 API (`/v1/...`), or runs on built-in synthetic demo data.

```bash
cd frontend && npm install
npm run dev        # http://localhost:5173, proxies /v1 to http://127.0.0.1:8000 (AKASH_API_URL to change)
npm test           # 31 tests: light-curve math, SSE parsing and resume, demo scenarios, HTTP client
npm run build
```

**Demo data** is the default (set `VITE_DEFAULT_MODE=live` to default to the API). Settings (the chip in the
top bar) switches to a live API and takes an API key, which is kept in `sessionStorage` only. Demo
star IDs (`TIC 900000001` to `900000008`) do not exist in any archive, and a permanent banner says so.

What is here: the logbook and search, a live investigation view (one lane per pipeline phase, streamed over
fetch-based SSE with resume), light curve and folded curve, separate readouts (no combined score),
the evidence strip (one lane per evidence channel), a provenance graph and the model registry.
Red-lamp mode (top bar) is a dark-adapted theme; every mark also differs by shape, not only colour.

Not here yet: object explorer for arbitrary catalogs, sky map, research agent chat, reports, experiment lab.
