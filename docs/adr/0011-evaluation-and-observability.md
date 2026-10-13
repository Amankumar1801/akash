# ADR 0011: Evaluation lab, observability and human review

Status: accepted (Phase 10)

## Evaluation (`akash_eval`, `/v1/experiments`)
Injection-recovery on top of the Phase 2 core: plant known trapezoid transits in noise light curves,
run the real pipeline, score recovery.

- Every rate carries a 95% Wilson interval. A bin with no trials has no rate (null), not zero.
- Reported: overall recovery, recovery by signal-to-noise, period and depth, aliases counted as
  misses and shown separately, SNR at 50% and 90% recovery (interpolated over bins with at least
  three trials, null if never reached) and a false-alarm rate on noise-only curves.
- The result carries a note and caveats stating that the noise is synthetic. The config enum only
  allows `synthetic`, so real-noise results cannot be claimed by editing a request. Adding real light
  curves as a noise source is a deliberate later change.
- Deterministic for a seed (chunks derive their own seeds). Config is hashed and stored with the result.
- Bounded: at most 60 trials and 20 controls, one active experiment per user, a separate low rate
  limit and a separate single-worker executor so experiments cannot starve investigations. Progress
  is persisted; cancel takes effect between chunks; orphaned experiments fail visibly on restart.

## Observability
- `Metrics`: in-process counters and fixed-bucket histograms with a per-metric series cap, so a
  labelling mistake becomes one overflow series, not unbounded memory. Labels are route templates,
  status classes and outcomes, never ids or users. `/v1/metrics` (admin) as JSON or Prometheus text.
- Counted: HTTP requests and latency, job outcomes and duration, agent runs (mode, fallback) and tool
  calls, reports, experiments.
- `/v1/investigations/{id}/trace`: one timeline merging the API requests that touched an
  investigation (with request ids that match the access log and audit log) and the job's own events.
  The investigation id is the trace id.

## Human review
Five labels (interesting, not interesting, false positive, needs follow-up, uncertain), append-only,
with the triage category shown at review time stored beside each label. `/v1/labels/export` (admin)
returns the latest label per reviewer and investigation.

Active learning architecture: labels are the interface; nothing retrains automatically. A reviewed
step builds a training set from the export, trains a candidate model into the registry as a new
immutable version, and evaluates it with the Phase 3 and experiment-lab procedures before it is
promoted. Disagreement between labels and triage category is the signal for which cases to surface
next. A review queue endpoint is not built yet.

## Limits
- Metrics are per process and reset on restart; no tracing backend, no dashboards.
- Experiments use the in-process executor, so a restart loses a running experiment (it is marked
  failed). Real-data sensitivity is still unmeasured.
- Labels are single-reviewer facts; no adjudication or inter-reviewer agreement view yet.
