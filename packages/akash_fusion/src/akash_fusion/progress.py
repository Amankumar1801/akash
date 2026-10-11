"""Progress events emitted by long-running investigations (consumed by the job system / SSE).

The callback may raise `JobCancelled` to abort between phases; the exception propagates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PHASES = ("stellar_enrichment", "signal_search", "anomaly", "ml_inference", "cross_match",
          "evidence_fusion", "persist")
STATUSES = ("started", "completed", "failed", "skipped")


@dataclass(frozen=True)
class ProgressEvent:
    phase: str
    status: str  # started | completed | failed | skipped
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


ProgressCallback = Callable[[ProgressEvent], None]
