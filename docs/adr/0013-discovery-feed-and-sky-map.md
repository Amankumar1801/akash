# ADR 0013: Discovery feed, candidate cards and sky map

Status: accepted

## Context
Users need to see which finished investigations deserve attention first, and where investigated objects sit on the sky.
The blueprint forbids a combined score and forbids implying that rank means probability of being real.

## Decision
- The feed is a review queue. Order is a fixed, published rule: triage category in a fixed order
  (`new_signal_review`, `models_disagree`, `insufficient_data`, `known_candidate`, `likely_systematic`,
  `known_false_positive`, `known_confirmed`), then anomaly percentile descending, then recency. Missing values sort last.
  Every response carries the rule text and a caveat that the order is not a likelihood.
- Cards show each evidence strand separately (transit S/N band, anomaly percentile with its reference population, model
  prediction with interval, catalog status, data quality, vetting counts, conflicts, review state). No card has a score field.
- One card per object: the latest assessed investigation. Users see only their own investigations; admins see all.
- Filters are explicit parameters (category, hide known, minimum anomaly percentile, minimum S/N, review state, name,
  sort). There is no natural-language search.
- `GET /v1/sky` returns compact points (capped at 5000) for investigated objects only and says it is not a survey map.
- CSV export happens client-side and neutralises spreadsheet formulas (`= + - @`, tab, CR).
- The demo-mode client mirrors the server rules in `lib/feed.ts`, with parity tests.

## Consequences
- The feed scans at most 500 recent investigations per request and says so when truncated. A materialised table is the
  upgrade path if that limit matters.
- The map shows only what has been investigated, so it cannot be used to infer sky coverage.
