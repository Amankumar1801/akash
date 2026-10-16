"""Plain-language search over the candidate queue, without a language model.

The text is matched against a fixed table of phrases. Each match sets one explicit filter, and
every phrase the table does not understand is returned to the caller, so nothing is silently
ignored. The table is exported to JSON (scripts/export_nl_rules.py) and the browser demo runs the
same rules, so the two cannot drift. Patterns use only syntax that Python and JavaScript share.

Rule actions:
  category   add triage categories              flag      set a boolean filter
  set        set reviewed / sort                min_anomaly, min_snr   fixed threshold
  *_capture  threshold from regex group 1       query     name search from groups 1 and 2
  unsupported  recognised but not expressible as a filter
"""

from __future__ import annotations

import re
from typing import Any

MAX_TEXT = 200
NUM = r"(\d+(?:\.\d+)?)"
CMP = r"(?:>=|>|above|over|at least|greater than|exceeding|exceeds|more than)?\s*"

RULES: list[dict[str, Any]] = [
    {
        "pattern": r"\bnot (?:yet )?(?:reviewed|looked at)(?: by me)?\b|\bunreviewed\b"
        r"|\b(?:haven't|havent|have not) (?:reviewed|looked at)\b|\bto review\b",
        "action": {"set": "reviewed", "value": "unreviewed"},
        "says": "review state: not reviewed by you",
    },
    {
        "pattern": r"\b(?:already )?reviewed(?: by me)?\b",
        "action": {"set": "reviewed", "value": "reviewed"},
        "says": "review state: reviewed by you",
    },
    {
        "pattern": r"\bnot (?:in|listed in|found in) (?:any |a |the )?catalou?gs?\b"
        r"|\buncatalou?ged\b"
        r"|\bnot (?:already )?known\b|\bhide known\b|\bexclude known\b",
        "action": {"flag": "exclude_known"},
        "says": "hide objects already in a catalog",
    },
    {
        "pattern": r"\b(?:known|catalogued|cataloged) candidates?\b",
        "action": {"category": ["known_candidate"]},
        "says": "category: already a catalogued candidate",
    },
    {
        "pattern": r"\bfalse positives?\b",
        "action": {"category": ["known_false_positive"]},
        "says": "category: catalogued as a false positive",
    },
    {
        "pattern": r"\bconfirmed(?: planets?)?\b",
        "action": {"category": ["known_confirmed"]},
        "says": "category: already a confirmed planet",
    },
    {
        "pattern": r"\bnew(?: signals?| candidates?| ones| objects?)?\b|\bunlisted\b"
        r"|\bworth (?:a )?(?:human )?look\b|\bnew_signal_review\b",
        "action": {"category": ["new_signal_review"]},
        "says": "category: unlisted signal, worth a look",
    },
    {
        "pattern": r"\bknown\b",
        "action": {"category": ["known_confirmed", "known_candidate", "known_false_positive"]},
        "says": "category: any already-known object",
    },
    {
        "pattern": r"\b(?:models? )?disagree\w*\b|\bconflicting models\b",
        "action": {"category": ["models_disagree"]},
        "says": "category: models disagree",
    },
    {
        "pattern": r"\binsufficient data\b|\bnot enough data\b|\bpoor data\b",
        "action": {"category": ["insufficient_data"]},
        "says": "category: not enough data",
    },
    {
        "pattern": r"\bsystematics?\b|\binstrumental\b|\bartifacts?\b|\bartefacts?\b",
        "action": {"category": ["likely_systematic"]},
        "says": "category: probably instrumental or stellar",
    },
    {
        "pattern": r"\banomal\w*(?: percentile)?\s*" + CMP + NUM,
        "action": {"min_anomaly_capture": 1},
        "says": "anomaly percentile at least {1}",
    },
    {
        "pattern": CMP + NUM + r"(?:st|nd|rd|th)? percentile\b",
        "action": {"min_anomaly_capture": 1},
        "says": "anomaly percentile at least {1}",
    },
    {
        "pattern": r"\bmost anomalous\b|\b(?:sort(?:ed)? )?by anomaly\b",
        "action": {"set": "sort", "value": "anomaly"},
        "says": "sort by anomaly percentile",
    },
    {
        "pattern": r"\bhigh(?:ly)? anomal\w*\b|\bvery anomalous\b|\banomalous\b|\bunusual\b",
        "action": {"min_anomaly": 90},
        "says": "anomaly percentile at least 90",
    },
    {
        "pattern": r"\b(?:snr|s/n|signal[- ]to[- ]noise)\s*" + CMP + NUM,
        "action": {"min_snr_capture": 1},
        "says": "signal-to-noise at least {1}",
    },
    {
        "pattern": r"\bstrongest\b|\bby (?:snr|signal strength)\b",
        "action": {"set": "sort", "value": "snr"},
        "says": "sort by signal-to-noise",
    },
    {
        "pattern": r"\bstrong signals?\b|\bhigh snr\b|\bstrong\b",
        "action": {"min_snr": 15},
        "says": "signal-to-noise at least 15 (a strong signal)",
    },
    {
        "pattern": r"\bmoderate(?: or stronger)?(?: signals?)?\b",
        "action": {"min_snr": 7},
        "says": "signal-to-noise at least 7 (moderate or stronger)",
    },
    {
        "pattern": r"\bweak(?:est)?(?: signals?)?\b",
        "action": {
            "unsupported": "there is no filter for weak signals; sort by signal-to-noise instead"
        },
        "says": "not supported",
    },
    {
        "pattern": r"\bmost recent\b|\blatest\b|\bnewest\b|\brecently\b|\bby (?:date|recency)\b",
        "action": {"set": "sort", "value": "recent"},
        "says": "sort by most recent",
    },
    {
        "pattern": r"\b(tic|kic|epic|toi|koi)[ -]?(\d+)\b",
        "action": {"query": "{1} {2}"},
        "says": "name contains {1} {2}",
    },
]

STOP = frozenset(
    "a an the and or of for to in on with that which who are is was be been "
    "have has had show me find "
    "list get give all any only those these ones one it its my i please objects object stars star "
    "targets target signals signal candidates candidate investigations "
    "investigation results result "
    "than at by from as about where what whose".split()
)


def _set_max(cur: float | None, v: float) -> float:
    return v if cur is None else max(cur, v)


def interpret(text: str) -> dict[str, Any]:
    text = text[:MAX_TEXT]
    work = text.lower()
    cats: set[str] = set()
    f: dict[str, Any] = {
        "exclude_known": False,
        "min_anomaly_percentile": None,
        "min_snr": None,
        "reviewed": "any",
        "q": None,
        "sort": "triage",
    }
    understood: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []
    notes: list[str] = []
    sort_set = False
    for rule in RULES:
        rx = re.compile(rule["pattern"], re.IGNORECASE)
        while True:
            m = rx.search(work)
            if m is None or m.end() == m.start():
                break
            phrase = work[m.start() : m.end()].strip()
            work = work[: m.start()] + " " * (m.end() - m.start()) + work[m.end() :]
            a = rule["action"]
            g = [m.group(i) for i in range(1, (rx.groups or 0) + 1)]
            says = rule["says"]
            for i, val in enumerate(g, 1):
                says = says.replace(f"{{{i}}}", val.upper() if i == 1 and "query" in a else val)
            if "category" in a:
                cats.update(a["category"])
            elif "flag" in a:
                f[a["flag"]] = True
            elif "set" in a:
                if a["set"] == "sort":
                    if sort_set:
                        continue
                    sort_set = True
                f[a["set"]] = a["value"]
            elif "min_anomaly" in a or "min_anomaly_capture" in a:
                v = float(a.get("min_anomaly", g[0] if g else 0))
                if v > 100.0:
                    notes.append(f"{phrase}: percentiles stop at 100, so 100 was used")
                f["min_anomaly_percentile"] = _set_max(f["min_anomaly_percentile"], min(v, 100.0))
            elif "min_snr" in a or "min_snr_capture" in a:
                v = float(a.get("min_snr", g[0] if g else 0))
                if v > 1000.0:
                    notes.append(f"{phrase}: the limit is 1000, so 1000 was used")
                f["min_snr"] = _set_max(f["min_snr"], min(v, 1000.0))
            elif "query" in a:
                if f["q"] is None:
                    f["q"] = a["query"].replace("{1}", g[0].upper()).replace("{2}", g[1])
            elif "unsupported" in a:
                unsupported.append({"phrase": phrase, "why": a["unsupported"]})
                continue
            understood.append({"phrase": phrase, "effect": says})
    f["category"] = sorted(cats)
    left: list[str] = []
    for tok in re.findall(r"[a-z0-9_/.'-]+", work):
        tok = tok.strip(".'-")
        if tok and tok not in STOP and tok not in left:
            left.append(tok)
    return {
        "filters": f,
        "understood": understood,
        "unsupported": unsupported,
        "not_understood": left,
        "notes": notes,
    }
