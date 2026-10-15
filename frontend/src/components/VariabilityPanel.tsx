import type { VariabilityCharacter, VariabilityResult } from "../api/types";

const TEXT: Record<VariabilityCharacter, string> = {
  insufficient_data: "Not enough data to describe the variability.",
  no_significant_variability: "No variability beyond the measurement noise.",
  periodic_like: "Regular, periodic-like variation.",
  stochastic_aperiodic: "Irregular, random-walk-like variation.",
};

export function VariabilityPanel({ v }: { v: VariabilityResult }) {
  const ev = v.excess_variance, drw = v.damped_random_walk, per = v.periodicity;
  return (
    <section className="section" aria-label="Variability" style={{ marginTop: 22 }}>
      <h3 style={{ margin: 0 }}>How the brightness varies</h3>
      <p className="prose" style={{ marginTop: 6 }}>{TEXT[v.character]}{v.reason ? ` ${v.reason}.` : ""}</p>
      {ev && (
        <dl className="dgrid" style={{ marginTop: 10, maxWidth: 640 }}>
          <div><dt>Fractional variability</dt><dd className="num">{(ev.fvar * 100).toFixed(2)}%{ev.significant ? "" : " (not above the noise)"}</dd></div>
          {per && <div><dt>Strongest period</dt><dd className="num">{per.periodic && per.best_period_d ? `${per.best_period_d.toFixed(2)} d (${(per.n_cycles ?? 0).toFixed(1)} cycles)` : "none stands out from red noise"}</dd></div>}
          {drw && <div><dt>Damping timescale</dt><dd className="num">{drw.tau_d_days.toFixed(1)} d, {drw.tau_d_reliable ? "constrained" : "not constrained"}</dd></div>}
        </dl>
      )}
      {drw?.note && <p className="muted" style={{ fontSize: 13.5 }}>{drw.note}</p>}
      <p className="muted" style={{ fontSize: 13.5, maxWidth: "70ch" }}>{v.caveats.join(" ")}</p>
    </section>
  );
}
