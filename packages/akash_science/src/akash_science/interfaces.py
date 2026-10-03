"""Stable seams: swap BLS for TLS, or add vetting checks, without touching callers."""

from __future__ import annotations

from typing import Protocol

from .lightcurve.types import F64, TCE, StellarContext, VetContext, VetResult


class TransitSearcher(Protocol):
    def search(self, time: F64, flux: F64, sigma: float) -> list[TCE]: ...


class VettingCheck(Protocol):
    name: str

    def run(self, ctx: VetContext) -> VetResult: ...


__all__ = ["StellarContext", "TransitSearcher", "VetContext", "VettingCheck"]
