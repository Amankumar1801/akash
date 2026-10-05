"""Map the features driving an anomaly score to a coarse, human-meaningful category.
The category describes WHAT is unusual, never what it IS (no 'new object' claims)."""

from __future__ import annotations

GROUPS: dict[str, tuple[str, ...]] = {
    "unusual_dips": ("dip_fraction", "n_dips", "log10_deepest_dip_ppm", "n_slow_dips",
                     "log10_deepest_slow_dip_ppm"),
    "flare_dominated": ("flare_fraction", "n_flares", "log10_max_flare_ppm"),
    "high_amplitude_variability": ("log10_std_ppm", "log10_range_ppm", "trend_ppm_per_day"),
    "unusual_periodicity": ("ls_peak_power", "ls_log10_period", "ls_peak_ratio", "acf_1h",
                            "acf_6h", "acf_24h", "resid_ls_peak_power", "resid_ls_log10_period",
                            "resid_short_period_power"),
    "elevated_or_correlated_noise": ("resid_log10_std_ppm", "log10_noise_1h_ppm", "log10_beta"),
}
FEATURE_TO_GROUP = {f: g for g, fs in GROUPS.items() for f in fs}
# Distribution-shape moments are ambiguous (flares, dips and big amplitudes all move them), so
# they are shown as drivers but carry no vote. resid_skew votes by SIGN: negative = dips,
# positive = flares.
NEUTRAL = frozenset({"skew", "kurtosis"})
DOMINANCE = 0.5


def categorize(drivers: list[tuple[str, float]]) -> str:
    """drivers: (feature, |z|) for the top drivers. If one group carries more than half of the
    total weight it names the category; otherwise the anomaly is a multi-feature combination."""
    weight: dict[str, float] = {}
    for name, z in drivers:
        if name in NEUTRAL:
            continue
        if name == "resid_skew":
            g = "unusual_dips" if z < 0 else "flare_dominated"
        else:
            g = FEATURE_TO_GROUP.get(name, "other")
        weight[g] = weight.get(g, 0.0) + abs(z)
    total = sum(weight.values())
    if total <= 0:
        return "feature_combination_outlier"
    best = max(weight, key=lambda k: weight[k])
    return best if weight[best] / total > DOMINANCE and best != "other" \
        else "feature_combination_outlier"
