# ADR 0001: Modular monolith with typed evidence as the central contract
- Status: accepted

## Context
AKASH must keep scientific facts, model predictions, anomalies, and LLM interpretation
distinct, and make every result reproducible, while being buildable by one student.

## Decision
1. One deployable (FastAPI) + one worker pool. Domain logic lives in library packages
   with a one-way dependency order: core <- data <- science <- ml <- fusion <- agent/api/worker.
   Libraries never import web, queue, or LLM-vendor SDKs.
2. Every finding is an immutable, typed `Evidence` row with an epistemic channel and provenance.
   Invariants are enforced in `akash_core` (see tests): non-interpretation evidence needs
   provenance; interpretation must be LLM/human and must cite evidence; LLM output cannot
   claim archive-curated reliability.
3. `Assessment` forbids extra fields, so no combined "score" can be introduced silently.
   Triage vocabulary is a closed enum with no "discovery" value.

## Alternatives considered
Microservices (ops cost, no benefit at this scale); free-text findings (not auditable);
learned fusion score (no ground-truth outcomes to learn from).

## Consequences
New modules plug into interfaces; changing a core invariant requires a new ADR.
