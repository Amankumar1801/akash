"""Deterministic 1-D spectrum analysis: continuum, line detection, redshift candidates."""

from .analysis import (
    REST_LINES,
    InvalidSpectrum,
    SpectrumAnalysis,
    SpectrumParams,
    analyze_spectrum,
)

__all__ = [
    "REST_LINES",
    "InvalidSpectrum",
    "SpectrumAnalysis",
    "SpectrumParams",
    "analyze_spectrum",
]
