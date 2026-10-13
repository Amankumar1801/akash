"""Treating everything that came from outside as data, never as instructions.

Defence in depth, in this order of importance:
1. Structure: the agent has only read-only tools bound to one investigation, so a successful
   injection still cannot write, fetch, or reach another user's data.
2. Framing: tool output reaches the model as a JSON string inside an envelope the system prompt
   calls untrusted.
3. Redaction: string values that look like instructions are replaced before the model sees them.
4. Verification (verify.py): whatever the model says is checked against what was retrieved.
Pattern matching (3) is the weakest layer and is never relied on alone."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

REDACTED = "[removed: instruction-like text from an external source]"

_INJECTION = [re.compile(p, re.I) for p in (
    r"ignore (all |any |the )?(previous|prior|above|earlier)",
    r"disregard (all |any |the )?(previous|prior|above|earlier|instructions)",
    r"(new|updated|real) (instructions?|system prompt|rules?)",
    r"\bsystem prompt\b", r"\byou are now\b", r"\bact as\b", r"\bpretend (to be|you)\b",
    r"\b(reveal|print|show|repeat) (your|the) (prompt|instructions|rules)\b",
    r"</?\s*(system|assistant|tool|untrusted)[^>]*>", r"<\|[^|>]*\|>", r"\[/?INST\]",
    r"\bcall (the )?tool\b", r"\bfunction_call\b", r"\btool_calls?\b",
    r"\b(api[_ -]?key|secret|password|bearer)\b\s*[:=]",
)]
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")


def clean_text(s: str, max_len: int = 400) -> str:
    """Normalise, strip control and bidirectional-override characters, and cap the length."""
    s = unicodedata.normalize("NFKC", s)
    s = _CONTROL.sub("", s)
    return s[:max_len]


def looks_like_injection(s: str) -> bool:
    return any(p.search(s) for p in _INJECTION)


def sanitize(obj: Any, stats: dict[str, int] | None = None, max_len: int = 400) -> Any:
    """Return a copy with every string cleaned and instruction-like strings redacted."""
    st = stats if stats is not None else {}
    if isinstance(obj, str):
        c = clean_text(obj, max_len)
        if looks_like_injection(c):
            st["redactions"] = st.get("redactions", 0) + 1
            return REDACTED
        return c
    if isinstance(obj, dict):
        return {clean_text(str(k), 80): sanitize(v, st, max_len) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v, st, max_len) for v in obj]
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return clean_text(str(obj), max_len)


def envelope(tool: str, payload: Any, max_chars: int) -> tuple[str, bool]:
    """Serialise tool output for the model; returns (text, truncated)."""
    body = json.dumps({"tool": tool, "untrusted_data": payload}, ensure_ascii=True,
                      separators=(",", ":"))
    if len(body) <= max_chars:
        return body, False
    cut = json.dumps({"tool": tool, "truncated": True,
                      "untrusted_data": "output too large; ask for a narrower selection"})
    return cut, True
