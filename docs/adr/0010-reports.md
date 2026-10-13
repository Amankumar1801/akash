# ADR 0010: Deterministic scientific reports

Status: accepted (Phase 9)

## Decision
`akash_report` builds the report from stored data only (assessment, evidence matrix, provenance).
No model writes any of it, so it cannot add claims. Writing is not the hard part of a report;
traceability is, and a template over typed evidence gives that for free.

- Thirteen sections in the blueprint's order. Empty sections say "Nothing was recorded" rather
  than disappearing.
- Facts, model outputs and interpretations are separate block kinds. Interpretations come only from
  stored `interpretation` evidence (written by an LLM or a person) and are labelled with the author.
  With none stored, the section says no AI-generated reading exists.
- Every content block cites existing evidence ids. Citations to unknown ids are dropped.
- Text from outside is cleaned and redacted if instruction-like; blocks whose wording asserts a
  discovery, new planet or certainty are withheld and counted in the report.
- `content_sha256` covers everything except the timestamp, so re-running on unchanged data gives the
  same hash.
- Renderers: Markdown (special characters escaped) and HTML (everything escaped, no script, no remote
  assets; served with `default-src 'none'; sandbox` and as an attachment).

API: `POST /v1/reports {investigation_id, format: json|markdown|html}`. Viewer role, owner-only
(404 otherwise), 409 until finished, own rate limit, audited with the content hash prefix.

## Consequences
- Reports are plain and repetitive by design. An LLM-written narrative layer could be added later
  as interpretation evidence, which the existing invariants already constrain.
- The section 3 to 6 text is the evidence's own recorded observation, so report quality is bounded by
  how well the pipeline words them.
- No PDF output yet (print the HTML). The demo-mode report in the frontend is a shorter,
  client-side version, not the server's.
