# ADR 0009: Research agent with guardrails

Status: accepted (Phase 8)

## Context
Users want to ask questions about an investigation. A model can phrase answers, but the blueprint
requires deterministic code for science, source attribution, tool permissions, prompt-injection
defences and honest uncertainty. Evidence text comes from outside (catalogs, headers), so it is
untrusted.

## Decision
`akash_agent` is a bounded loop: the model proposes tool calls and a final answer; deterministic
code decides what runs and what is returned.

1. **Structure first.** Tools are read-only, typed (pydantic, `extra=forbid`) and bound to one
   investigation through the `InvestigationView` protocol. The registry refuses any tool that is not
   `read_only`. A `ToolPolicy` allowlist limits the set per call. The model cannot name another
   investigation, a path, a URL or a query. A fully successful injection therefore cannot write,
   fetch or cross tenants.
2. **Untrusted data framing.** Tool output is sanitised (NFKC, control and bidi characters removed,
   length capped), instruction-like strings are redacted, and the result is a JSON envelope under
   `untrusted_data`. This is the weakest layer (pattern matching) and nothing relies on it alone.
3. **Verified, cited output.** The final answer is JSON: statements with a `kind` and
   `evidence_ids`. `verify()` checks that cited ids exist and were retrieved with a tool; facts cite
   measurement, catalog or quality rows (not model outputs); predictions cite model rows and come
   with an uncertainty statement; numbers appear in the cited evidence; "confirmed" needs a
   catalog row with that status; discovery, new-planet, certainty and life claims are rejected
   (negated phrasing allowed).
4. **Never unverified.** One repair round, then a deterministic answer built from the evidence's
   own recorded observations. With no provider configured the deterministic answer is the normal mode.
5. **Budgets.** Model calls, tool calls, tool-output size, question length, wall-clock time,
   provider retries. A separate per-principal rate limit (`api_agent_rate_per_min`).
6. **Provider seam.** `LLMProvider` protocol; `OpenAICompatProvider` (OpenAI, OpenRouter, vLLM,
   Ollama) over httpx; errors never include response bodies or keys.

API: `POST /v1/investigations/{id}/ask` (viewer role, owner-only via 404, 409 until finished,
audited as `agent.ask` with `mode:ok|fallback`).

## Consequences
- Write tools (for example saving an interpretation as evidence) are deliberately absent. They
  need an approval workflow and are deferred.
- The verifier checks consistency with retrieved evidence, not truth of the evidence, and cannot
  catch a subtly misleading but supported sentence. It reduces, not eliminates, model risk.
- The deterministic answer does not tailor itself to the question.
- No live model has been exercised; the provider is tested against a mock transport only.
