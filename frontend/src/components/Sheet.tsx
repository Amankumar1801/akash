import type { Assessment, VetStatus } from "../api/types";
import { days, pct, ppm } from "../lib/format";
import { vetName, VET } from "../lib/labels";
import { VetGlyph } from "./Glyphs";

function Ruler({ lo, hi, at, unit, label }: { lo: number; hi: number | null; at: number; unit: string; label: string }) {
  return (
    <div className="ruler" role="img" aria-label={label}>
      <div className="track" />
      {hi !== null && <div className="band" style={{ left: `${lo}%`, width: `${Math.max(hi - lo, 0.8)}%` }} />}
      <div className="pin" style={{ left: `${at}%` }} />
      <div className="scale"><span>0{unit}</span><span>50{unit}</span><span>100{unit}</span></div>
    </div>
  );
}

const ORDER: VetStatus[] = ["fail", "warn", "unknown", "pass"];

/** Separate readouts on purpose. There is no combined score and nothing here is added up. */
export function Sheet({ a }: { a: Assessment }) {
  const p = a.prediction, an = a.anomaly, tr = a.transit;
  const vets = Object.entries(a.vetting).sort((x, y) => ORDER.indexOf(x[1]) - ORDER.indexOf(y[1]));
  return (
    <div className="sheet">
      {tr && (
        <div className="cell">
          <h3>The signal</h3>
          <div className="big num">{days(tr.period_d.value)}</div>
          <dl className="dl" style={{ marginTop: 12 }}>
            <dt>Period range</dt><dd>{tr.period_d.lo.toFixed(3)} to {tr.period_d.hi.toFixed(3)} d</dd>
            <dt>Depth</dt><dd>{ppm(tr.depth_ppm)}</dd>
            <dt>Duration</dt><dd>{tr.duration_h.toFixed(1)} h</dd>
            <dt>Transits seen</dt><dd>{tr.n_transits}</dd>
            <dt>Signal to noise</dt><dd>{tr.snr.toFixed(1)}</dd>
          </dl>
        </div>
      )}
      {p && (
        <div className="cell">
          <h3>Classifier</h3>
          <div className="big num">{pct(p.planet_like_probability)}<small>planet-like</small></div>
          <Ruler lo={p.interval_90[0] * 100} hi={p.interval_90[1] * 100} at={p.planet_like_probability * 100} unit="%"
            label={`Probability ${pct(p.planet_like_probability)}, 90 percent set ${pct(p.interval_90[0])} to ${pct(p.interval_90[1])}`} />
          <p className="note">
            The shaded set is the range the model keeps plausible at 90% coverage.{" "}
            {p.calibrated ? `Probabilities are calibrated (${p.calibration_method}).` : "Probabilities are not calibrated."}
            {p.disagreement?.flag ? ` The models disagree by ${pct(p.disagreement.range)}.` : ""}
          </p>
        </div>
      )}
      {an && (
        <div className="cell">
          <h3>How unusual</h3>
          <div className="big num">{Math.round(an.percentile)}<small>th percentile</small></div>
          <Ruler lo={0} hi={null} at={an.percentile} unit="" label={`${Math.round(an.percentile)}th percentile of the reference population`} />
          <p className="note">Compared with {an.reference_population}. Unusual does not mean a planet, and it does not mean a discovery.</p>
        </div>
      )}
      <div className="cell w6">
        <h3>Vetting checks</h3>
        <ul className="vets">
          {vets.map(([k, v]) => (
            <li key={k}><VetGlyph s={v} /><span>{vetName(k)}</span><span className="res">{VET[v]}</span></li>
          ))}
        </ul>
      </div>
      <div className="cell w3">
        <h3>Data quality</h3>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <span className="grade" aria-label={`Grade ${a.data_quality.grade}`}>{a.data_quality.grade}</span>
          <span className="note" style={{ marginTop: 0 }}>{a.data_quality.reasons.join(". ") || "No quality concerns recorded."}</span>
        </div>
        {a.ood && <p className="note">{a.ood.flag
          ? "Out of distribution: this signal looks unlike the data the classifier learned from, so lean on vetting and a manual look."
          : "Within the range of data the classifier was trained on."}</p>}
      </div>
      <div className="cell w3">
        <h3>What the catalogs say</h3>
        {a.known_status ? (
          <>
            <div className="big" style={{ fontSize: 28 }}>{{ none: "No entry", confirmed: "Confirmed planet", candidate: "Candidate",
              false_positive: "False positive" }[a.known_status.status] ?? a.known_status.status}</div>
            <p className="note">{a.known_status.source}, checked {new Date(a.known_status.retrieved_at).toLocaleString()}.</p>
          </>
        ) : <p className="note">The lookup did not run, so this is unknown rather than "no entry".</p>}
      </div>
      {a.recommended_followup.length > 0 && (
        <div className="cell w12">
          <h3>Suggested follow-up</h3>
          <ul className="followups">{a.recommended_followup.map((f) => <li key={f}>{f}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
