"""Export the plain-language search rules and parity cases for the browser demo.

    uv run --no-sync python scripts/export_nl_rules.py

Writes frontend/src/lib/nl_rules.json (the rule table) and frontend/src/test/nl_cases.json (inputs with
the answers the Python engine gives). The frontend test runs its engine over the same cases.
"""
from __future__ import annotations

import json
from pathlib import Path

from akash_api.nlquery import MAX_TEXT, RULES, STOP, interpret

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src"
CASES = [
    "show me new strong signals not in a catalog with anomaly above 95",
    "unreviewed TIC 900000001 most recent",
    "weak signals that are anomalous and flasky",
    "known candidates snr over 10",
    "systematic artifacts, models disagree",
    "top 95th percentile",
    "anomaly 150",
    "not reviewed by me",
    "already reviewed",
    "known false positives",
    "confirmed planets",
    "insufficient data",
    "strongest first",
    "most anomalous",
    "signal-to-noise at least 20 and anomaly percentile 80",
    "snr > 8.5",
    "KIC 8462852",
    "hide known, moderate or stronger",
    "banana",
    "",
    "   ",
    "NEW NEW new",
    "worth a human look, latest",
]


def main() -> None:
    (ROOT / "lib" / "nl_rules.json").write_text(json.dumps(
        {"max_text": MAX_TEXT, "stop": sorted(STOP), "rules": RULES}, indent=1))
    cases = [{"text": t, "expect": interpret(t)} for t in CASES]
    (ROOT / "test" / "nl_cases.json").write_text(json.dumps(cases, indent=1))
    print(f"{len(RULES)} rules, {len(cases)} cases")


if __name__ == "__main__":
    main()
