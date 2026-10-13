"""Plain data types shared by the provider seam, the agent loop and the verifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# What a sentence in an answer *is*. The verifier holds each kind to a different standard.
Kind = Literal["fact", "prediction", "interpretation", "uncertainty", "recommendation"]


class Statement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=600)
    kind: Kind
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)


class AgentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statements: list[Statement] = Field(min_length=1, max_length=14)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


@dataclass(frozen=True)
class LLMReply:
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str
    statement: int | None = None


@dataclass(frozen=True)
class Budget:
    max_llm_calls: int = 6
    max_tool_calls: int = 10
    max_tool_output_chars: int = 6000
    max_question_chars: int = 500
    timeout_s: float = 45.0
    max_repairs: int = 1
    provider_retries: int = 1


@dataclass
class TraceStep:
    kind: Literal["llm", "tool", "denied", "verify", "repair", "fallback"]
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    answer: AgentAnswer
    mode: Literal["llm", "deterministic"]
    verified: bool
    fallback_reason: str | None
    trace: list[TraceStep]
    retrieved_evidence_ids: list[str]
