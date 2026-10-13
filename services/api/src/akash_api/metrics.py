"""In-process metrics: counters and fixed-bucket histograms, safe for threads.

Labels must be low-cardinality (route templates, status classes, outcomes), never ids, users or
free text. A per-metric series cap turns accidental cardinality bugs into a visible overflow
series instead of unbounded memory. Single-process by design; a multi-instance deployment scrapes
each instance (Prometheus text format is provided)."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import TypeVar

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0)
MAX_SERIES = 200
Labels = tuple[tuple[str, str], ...]
V = TypeVar("V")


def _key(labels: dict[str, str] | None) -> Labels:
    return tuple(sorted((k, str(v)[:64]) for k, v in (labels or {}).items()))


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[Labels, float]] = defaultdict(dict)
        self._hist: dict[str, dict[Labels, list[float]]] = defaultdict(dict)  # buckets..., sum, n

    def _slot(self, table: dict[Labels, V], key: Labels) -> Labels:
        return key if key in table or len(table) < MAX_SERIES else (("_overflow", "true"),)

    def inc(self, name: str, labels: dict[str, str] | None = None, by: float = 1.0) -> None:
        with self._lock:
            t = self._counters[name]
            k = self._slot(t, _key(labels))
            t[k] = t.get(k, 0.0) + by

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            t = self._hist[name]
            k = self._slot(t, _key(labels))
            h = t.setdefault(k, [0.0] * (len(BUCKETS) + 2))
            for i, b in enumerate(BUCKETS):
                if value <= b:
                    h[i] += 1
            h[-2] += value
            h[-1] += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "counters": {n: [{"labels": dict(k), "value": v} for k, v in t.items()]
                             for n, t in self._counters.items()},
                "histograms": {n: [{"labels": dict(k), "count": h[-1], "sum": round(h[-2], 6),
                                    "buckets": dict(zip((str(b) for b in BUCKETS), h[:-2],
                                                        strict=True))}
                                   for k, h in t.items()] for n, t in self._hist.items()},
            }

    def prometheus(self) -> str:
        out: list[str] = []
        with self._lock:
            for n, ct in sorted(self._counters.items()):
                out.append(f"# TYPE akash_{n} counter")
                for k, v in ct.items():
                    lab = ",".join(f'{a}="{_esc(b)}"' for a, b in k)
                    out.append(f"akash_{n}{{{lab}}} {v:g}")
            for n, ht in sorted(self._hist.items()):
                out.append(f"# TYPE akash_{n} histogram")
                for k, h in ht.items():
                    base = [f'{a}="{_esc(b)}"' for a, b in k]
                    for b, c in zip(BUCKETS, h[:-2], strict=True):
                        out.append(_line(n, "bucket", [*base, 'le="' + format(b, "g") + '"'], c))
                    out.append(_line(n, "bucket", [*base, 'le="+Inf"'], h[-1]))
                    out.append(_line(n, "sum", base, h[-2]))
                    out.append(_line(n, "count", base, h[-1]))
        return "\n".join(out) + "\n"


def _line(name: str, suffix: str, labels: list[str], value: float) -> str:
    return "akash_" + name + "_" + suffix + "{" + ",".join(labels) + "} " + format(value, "g")
