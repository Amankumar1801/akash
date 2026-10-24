import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { DiscoveryCard, ReviewLabel } from "../api/types";
import { TRIAGE, VET } from "../lib/labels";
import { CaseArt, KIND_BY_CATEGORY } from "./Scene";

const REVIEW_TEXT: Record<ReviewLabel, string> = {
  interesting: "Interesting", not_interesting: "Not interesting", false_positive: "False positive",
  needs_followup: "Needs follow-up", uncertain: "Uncertain",
};
const STRENGTH = { none: "No signal", weak: "Weak signal", moderate: "Moderate signal", strong: "Strong signal" } as const;

export function DiscoveryCardView({ c, picked, onPick, onReviewed, onReport, busy, index = 0 }: {
  index?: number; c: DiscoveryCard; picked: boolean; onPick: () => void; onReviewed: () => void; onReport: () => void; busy: boolean;
}) {
  const t = TRIAGE[c.triage_category];
  // A short confirmation only when the stored review state really changed, not on first render.
  const prev = useRef(c.review.mine);
  const [just, setJust] = useState(false);
  useEffect(() => {
    if (prev.current === c.review.mine) return;
    prev.current = c.review.mine;
    setJust(true);
    const id = window.setTimeout(() => setJust(false), 1100);
    return () => window.clearTimeout(id);
  }, [c.review.mine]);
  return (
    <article className="dcard" aria-label={`Candidate ${c.name}`} data-just-reviewed={just || undefined}
      style={{ ["--i" as string]: Math.min(index, 9) }}>
      <CaseArt kind={KIND_BY_CATEGORY[c.triage_category]} seed={index + 1} className="caseart dthumb" />
      <header>
        <h3>{c.name}</h3>
        <span className={`dcat tone-${t.tone}`}>{t.title}</span>
      </header>
      <dl className="dgrid">
        <div><dt>Transit signal</dt><dd>{STRENGTH[c.signal_strength]}{c.transit && <span className="num"> · S/N {c.transit.snr.toFixed(1)}, {c.transit.period_d.toFixed(2)} d</span>}</dd></div>
        <div><dt>Anomaly</dt><dd>{c.anomaly ? <><span className="num">{Math.round(c.anomaly.percentile)}th percentile</span> <span className="muted">of {c.anomaly.reference_population}</span></> : "not computed"}</dd></div>
        <div><dt>Model prediction</dt><dd>{c.prediction ? <span className="num">{(c.prediction.probability * 100).toFixed(0)}% (90% interval {(c.prediction.interval_90[0] * 100).toFixed(0)} to {(c.prediction.interval_90[1] * 100).toFixed(0)}%){c.prediction.calibrated ? "" : ", uncalibrated"}{c.prediction.models_disagree ? ", models disagree" : ""}</span> : "none"}</dd></div>
        <div><dt>Catalog status</dt><dd>{c.known_status ? `${c.known_status.replace(/_/g, " ")} (${c.known_source ?? "archive"})` : "not checked"}</dd></div>
        <div><dt>Data quality</dt><dd>Grade {c.data_quality}</dd></div>
        <div><dt>Vetting</dt><dd className="num">{c.vetting.pass ?? 0} {VET.pass.toLowerCase()}, {c.vetting.warn ?? 0} {VET.warn.toLowerCase()}, {c.vetting.fail ?? 0} {VET.fail.toLowerCase()}</dd></div>
        <div><dt>Conflicting evidence</dt><dd>{c.n_conflicts ? `${c.n_conflicts} item${c.n_conflicts > 1 ? "s" : ""}` : "none recorded"}</dd></div>
        <div><dt>Review</dt><dd>{c.review.mine ? `You: ${REVIEW_TEXT[c.review.mine]}` : "Not reviewed by you"}{c.review.n_reviewers > 1 ? ` · ${c.review.n_reviewers} reviewers` : ""}</dd></div>
      </dl>
      {c.recommended_followup.length > 0 && <p className="muted dfollow">Suggested follow-up: {c.recommended_followup.join("; ")}</p>}
      <footer>
        <Link className="btn" to={`/investigations/${c.investigation_id}`}>Open investigation</Link>
        <button className="btn" onClick={onReport} disabled={busy}>Report</button>
        <button className="btn" onClick={onReviewed} disabled={busy} aria-pressed={!!c.review.mine}>{c.review.mine ? "Reviewed" : "Mark as reviewed"}</button>
        <label className="dpick"><input type="checkbox" checked={picked} onChange={onPick} /> Compare</label>
      </footer>
    </article>
  );
}
