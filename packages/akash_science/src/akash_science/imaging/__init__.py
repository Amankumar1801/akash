"""Single-band image analysis: background, source detection and standard morphology descriptors."""

from .morphology import (
    ImageAnalysis,
    InvalidImage,
    analyze_image,
    downsample_for_preview,
    read_fits_bytes,
)

__all__ = [
    "ImageAnalysis",
    "InvalidImage",
    "analyze_image",
    "downsample_for_preview",
    "read_fits_bytes",
]
