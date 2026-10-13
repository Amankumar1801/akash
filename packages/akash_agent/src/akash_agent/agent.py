"""The bounded agent loop: model proposes, deterministic code disposes.

Guarantees, regardless of what the model does or what the data says:
- only read-only, policy-allowed tools bound to one investigation can run;
- limits on model calls, tool calls, output size, question size and wall-clock time;
- the returned answer has passed verify(); otherwise it is the deterministic answer."""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import ValidationError

from . import guard
from .deterministic import build as deterministic_answer
from .prompt import REPAIR, SYSTEM
from .provider import LLMProvider, ProviderError
from .tools import ToolError, ToolPolicy, ToolRegistry
from .types import AgentAnswer, AgentResult, Budget, Message, ToolCall, TraceStep, Violation
from .verify import verify
from .view import InvestigationView


def _extract_json(text: str) -> Any:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object")
    return json.loads(t[start:end + 1])


class ResearchAgent:
    def __init__(self, provider: LLMProvider | None, registry: ToolRegistry | None = None,
                 policy: ToolPolicy | None = None, budget: Budget | None = None) -> None:
        self.provider = provider
        self.registry = registry or ToolRegistry()
        self.policy = policy or ToolPolicy()
        self.budget = budget or Budget()

    # -- public -------------------------------------------------------------------------------
    def ask(self, question: str, view: InvestigationView) -> AgentResult:
        q = guard.clean_text(question, self.budget.max_question_chars).strip()
        trace: list[TraceStep] = []
        if not q:
            return self._fallback(view, "empty question", trace, [])
        if self.provider is None:
            return self._fallback(view, "no model configured", trace, [], quiet=True)
        try:
            return self._run(q, view, trace)
        except ProviderError as e:
            return self._fallback(view, f"model unavailable: {e}", trace, [])
        except TimeoutError:
            return self._fallback(view, "time limit reached", trace, [])

    # -- loop ---------------------------------------------------------------------------------
    def _run(self, q: str, view: InvestigationView, trace: list[TraceStep]) -> AgentResult:
        assert self.provider is not None
        b = self.budget
        deadline = time.monotonic() + b.timeout_s
        rows = {r["evidence_id"].lower(): r for r in view.evidence()}
        seen: set[str] = set()
        msgs = [Message("system", SYSTEM), Message("user", q)]
        specs = self.registry.specs(self.policy)
        llm_calls = tool_calls = repairs = 0

        while True:
            if llm_calls >= b.max_llm_calls:
                return self._fallback(view, "model call limit reached", trace, sorted(seen))
            reply = self._complete(msgs, specs, deadline)
            llm_calls += 1
            trace.append(TraceStep("llm", {"tool_calls": [c.name for c in reply.tool_calls],
                                           "has_text": bool(reply.text)}))
            if reply.tool_calls:
                msgs.append(Message("assistant", reply.text or "", reply.tool_calls))
                for call in reply.tool_calls:
                    msgs.append(self._tool(call, view, seen, trace, tool_calls >= b.max_tool_calls))
                    tool_calls += 1
                continue

            problems: list[Violation]
            try:
                answer = AgentAnswer.model_validate(_extract_json(reply.text or ""))
                problems = verify(answer, rows, seen)
            except (ValueError, ValidationError):
                answer = None
                problems = [Violation("bad_format", "reply was not the required JSON")]
            trace.append(TraceStep("verify", {"ok": not problems,
                                              "codes": sorted({p.code for p in problems})}))
            if not problems and answer is not None:
                return AgentResult(answer, "llm", True, None, trace, sorted(seen))
            if repairs >= b.max_repairs:
                codes = ", ".join(sorted({p.code for p in problems}))
                return self._fallback(view, "answer failed verification: " + codes, trace,
                                      sorted(seen))
            repairs += 1
            trace.append(TraceStep("repair", {"codes": sorted({p.code for p in problems})}))
            msgs.append(Message("assistant", reply.text or ""))
            msgs.append(Message("user", REPAIR.format(
                problems="; ".join(f"{p.code}: {p.detail}" for p in problems[:5]))))

    def _complete(self, msgs: list[Message], specs: Any, deadline: float):  # type: ignore[no-untyped-def]
        assert self.provider is not None
        err: ProviderError | None = None
        for _ in range(self.budget.provider_retries + 1):
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError
            try:
                return self.provider.complete(msgs, specs, min(left, self.budget.timeout_s))
            except ProviderError as e:
                err = e
        raise err  # type: ignore[misc]

    def _tool(self, call: ToolCall, view: InvestigationView, seen: set[str],
              trace: list[TraceStep], over_budget: bool) -> Message:
        b = self.budget
        if over_budget:
            trace.append(TraceStep("denied", {"tool": call.name, "why": "tool call limit"}))
            text, _ = guard.envelope(call.name, "tool call limit reached; answer now",
                                     b.max_tool_output_chars)
            return Message("tool", text, tool_call_id=call.id)
        try:
            res = self.registry.call(call.name, call.args, view, self.policy)
        except ToolError as e:
            trace.append(TraceStep("denied", {"tool": call.name, "why": str(e)[:120]}))
            text, _ = guard.envelope(call.name, {"error": str(e)}, b.max_tool_output_chars)
            return Message("tool", text, tool_call_id=call.id)
        stats: dict[str, int] = {}
        data = guard.sanitize(res.data, stats)
        text, truncated = guard.envelope(call.name, data, b.max_tool_output_chars)
        if not truncated:
            seen.update(e.lower() for e in res.seen_evidence)
        trace.append(TraceStep("tool", {"tool": call.name, "truncated": truncated,
                                        "redactions": stats.get("redactions", 0)}))
        return Message("tool", text, tool_call_id=call.id)

    def _fallback(self, view: InvestigationView, reason: str, trace: list[TraceStep],
                  seen: list[str], quiet: bool = False) -> AgentResult:
        trace.append(TraceStep("fallback", {"reason": reason}))
        ans = deterministic_answer(view.assessment(), view.evidence())
        return AgentResult(ans, "deterministic", True, None if quiet else reason, trace, seen)
