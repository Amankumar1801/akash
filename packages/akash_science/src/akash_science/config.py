from __future__ import annotations

from dataclasses import asdict, dataclass, field

from akash_core.ids import params_hash

PIPELINE_VERSION = "lc-pipeline@1"


@dataclass(frozen=True)
class QualityConfig:
    allowed_quality_bits: int = 0  # native flag bits tolerated (0 => any flagged cadence dropped)
    upper_clip_sigma: float = 5.0  # clip UPWARD outliers only; dips are never clipped
    max_gap_days: float = 0.5  # gaps longer than this split the light curve into segments
    min_segment_points: int = 50


@dataclass(frozen=True)
class DetrendConfig:
    window_days: float = 1.0  # rule of thumb: >= ~3x the longest transit duration searched
    grid_step_fraction: float = 0.1  # trend evaluated every window*fraction, then interpolated
    biweight_c: float = 5.0
    iterations: int = 5
    min_window_points: int = 10


@dataclass(frozen=True)
class SearchConfig:
    min_period_days: float = 0.5
    max_period_days: float | None = None  # default: baseline / min_transits
    durations_days: tuple[float, ...] = (0.04, 0.06, 0.09, 0.13, 0.2, 0.3)
    max_tces: int = 3
    snr_threshold: float = 7.1  # Kepler's MES threshold; a convention, not a physical constant
    min_transits: int = 2
    frequency_factor: float = 1.0
    max_periods: int = 150_000
    mask_factor: float = 1.5  # in-transit mask half-width multiplier for iterative search
    max_duty_cycle: float = 0.15  # reject duration/period above this (BLS red-noise artefacts)
    correct_red_noise: bool = True  # deflate SNR by the correlated-noise factor beta (Pont+2006)


@dataclass(frozen=True)
class ViewConfig:
    global_bins: int = 2001
    local_bins: int = 201
    local_width_durations: float = 4.0


@dataclass(frozen=True)
class PipelineConfig:
    quality: QualityConfig = field(default_factory=QualityConfig)
    detrend: DetrendConfig = field(default_factory=DetrendConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    view: ViewConfig = field(default_factory=ViewConfig)
    version: str = PIPELINE_VERSION

    def hash(self) -> str:
        return params_hash(asdict(self))
