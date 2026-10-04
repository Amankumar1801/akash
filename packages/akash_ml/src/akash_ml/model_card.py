from __future__ import annotations

from typing import Any


def _f(x: float) -> str:
    return "n/a" if x != x else f"{x:.3f}"


def render_model_card(meta: dict[str, Any], training_data_note: str) -> str:
    m = meta["metrics"]
    rows = "\n".join(
        f"| {r['name']} | {_f(r['pr_auc'])} ({_f(r['pr_auc_ci95'][0])}-{_f(r['pr_auc_ci95'][1])}) "
        f"| {_f(r['roc_auc'])} | {_f(r['brier'])} | {_f(r['ece'])} |"
        for r in m["models"].values())
    c, thr = m["conformal"], meta["threshold"]
    ap = m["models"]["council_calibrated"]["at_threshold"]
    return f"""# Model card: {meta['name']} {meta['version']}

**Task:** score whether a threshold-crossing event (TCE) looks planet-like. This is a
*triage score*, not a planet detection. It never establishes a discovery.

## Provenance
- Feature set `{meta['feature_version']}`; code `{meta['code_version']}`
- Training data hash `{meta['data_hash'][:16]}`;
  split manifest `{meta['split_manifest_digest'][:16]}`
- Rows: {meta['n']} (test positives: {meta['n_pos_test']})
- Training data: {training_data_note}

## Test performance (star-grouped bootstrap 95% CI for PR-AUC)
| Model | PR-AUC (95% CI) | ROC-AUC | Brier | ECE |
|---|---|---|---|---|
{rows}

Decision threshold {thr:.3f} (chosen on validation, frozen): precision {_f(ap['precision'])},
recall {_f(ap['recall'])}, F1 {_f(ap['f1'])}, FPR {_f(ap['fpr'])}.

## Uncertainty
- Calibration: {meta['calibration_method']}, fit on a held-out calibration split.
- Conformal sets (alpha={c['alpha']}): overall coverage {_f(c['coverage'])}; per class
  {', '.join(f'{k}: {_f(v)}' for k, v in c['class_coverage'].items())};
  uncertain {_f(c['frac_uncertain'])}, abstain {_f(c['frac_abstain'])}.
  The guarantee assumes exchangeability and does NOT hold under domain shift.
- OOD flag rate: test {_f(m['ood']['flag_rate_test'])} vs train {_f(m['ood']['flag_rate_train'])}.
- Council (cross-family) disagreement rate: {_f(m['council_disagreement_rate'])}.
- The reported 90% interval is ensemble spread (model uncertainty), not a label confidence
  interval.

## Known limitations
- Labels are catalog dispositions (partly pipeline-derived); the model can inherit their biases.
- Performance on a different mission/cadence (e.g. Kepler -> TESS) is NOT established here.
- Stellar-context features are unused until Gaia/TIC parameters are wired in (Phase 5).
- Recall by SNR/period/depth is in the evaluation JSON; low-SNR and long-period transits are
  the expected weak spots.
"""
