import { useEffect, useRef, useState } from "react";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { Experiment, ExperimentConfig, RecoveryBin, Rate } from "../api/types";
import { PageHead } from "../components/PageHead";

const DEFAULTS: ExperimentConfig = {
  n_trials: 20, n_controls: 6, seed: 0, period_min_d: 1, period_max_d: 10,
  depth_min_ppm: 500, depth_max_ppm: 8000, noise_source: "synthetic",
};
const pct = (r: Rate) => (r.rate === null ? "no data" : `${Math.round(r.rate * 100)}%`);
const ci = (r: Rate) => (r.lo === null || r.hi === null ? "" : ` (${Math.round(r.lo * 100)} to ${Math.round(r.hi * 100)}%)`);

function RecoveryChart({ bins }: { bins: RecoveryBin[] }) {
  const W = 640, H = 232, L = 44, B = 58, T = 12, R = 8, w = (W - L - R) / bins.length;
  const y = (v: number) => T + (1 - v) * (H - T - B);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" className="lab-chart" style={{ width: "100%", maxWidth: 760 }}
         aria-label="Recovery rate by signal-to-noise bin, with 95 percent intervals">
      {[0, 0.5, 1].map((v) => (
        <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--rule-soft)" />
          <text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--ink-3)">{Math.round(v * 100)}%</text></g>))}
      {bins.map((b, i) => {
        const cx = L + w * (i + 0.5), r = b.recovered;
        return (
          <g key={b.label}>
            {r.rate === null
              ? <text x={cx} y={y(0.5)} textAnchor="middle" fontSize="11" fill="var(--ink-3)">no data</text>
              : <><line x1={cx} x2={cx} y1={y(r.hi ?? 1)} y2={y(r.lo ?? 0)} stroke="var(--ink-3)" strokeWidth="2" />
                <circle cx={cx} cy={y(r.rate)} r="5" fill="var(--lamp)" /></>}
            <text x={cx} y={H - B + 16} textAnchor="middle" fontSize="11" fill="var(--ink-2)">{b.label.replace(" and above", "+")}</text>
            <text x={cx} y={H - B + 30} textAnchor="middle" fontSize="10.5" fill="var(--ink-3)">n = {r.n}</text>
          </g>);
      })}
      <text x={(L + W) / 2} y={H - 2} textAnchor="middle" fontSize="11" fill="var(--ink-3)">Expected signal-to-noise of the injected transit</text>
    </svg>
  );
}

function Table({ title, bins }: { title: string; bins: RecoveryBin[] }) {
  return (
    <div className="scroll-x"><table className="tbl">
      <caption className="muted" style={{ textAlign: "left", padding: "10px 0 4px" }}>{title}</caption>
      <thead><tr><th>Range</th><th>Trials</th><th>Recovered (95% interval)</th><th>Only an alias found</th></tr></thead>
      <tbody>{bins.map((b) => (
        <tr key={b.label} style={{ cursor: "default" }}><td>{b.label}</td><td className="num">{b.recovered.n}</td>
          <td className="rate">{pct(b.recovered)}{ci(b.recovered)}</td><td className="rate">{pct(b.alias_only)}</td></tr>))}</tbody>
    </table></div>
  );
}

export function Lab() {
  const { api } = useApi();
  const [cfg, setCfg] = useState<ExperimentConfig>(DEFAULTS);
  const [exp, setExp] = useState<Experiment | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const running = exp !== null && (exp.status === "queued" || exp.status === "running");

  useEffect(() => () => window.clearTimeout(timer.current), []);

  function poll(id: string) {
    timer.current = window.setTimeout(async () => {
      try {
        const e = await api.getExperiment(id);
        setExp(e);
        if (e.status === "queued" || e.status === "running") poll(id);
      } catch (x) { setErr(explain(x)); }
    }, 1500);
  }

  async function run(ev: React.FormEvent) {
    ev.preventDefault(); setErr(null); setExp(null);
    try { const e = await api.createExperiment(cfg); setExp(e); poll(e.experiment_id); }
    catch (x) { setErr(explain(x)); }
  }
  async function cancel() { if (exp) try { setExp(await api.cancelExperiment(exp.experiment_id)); } catch (x) { setErr(explain(x)); } }

  const num = (k: keyof ExperimentConfig) => (
    <input type="number" value={cfg[k] as number} step="any"
           onChange={(e) => setCfg({ ...cfg, [k]: Number(e.target.value) })} />);
  const r = exp?.result;

  return (
    <section className="section">
      <PageHead eyebrow="Lab" title="Run your own" accent="experiments.">
        Plant transits of known size in noisy light curves, run the real pipeline, and count how many it finds.
        This measures how sensitive the pipeline is, and how often it raises an alarm when nothing is there.
        The noise is synthetic, so the results describe the pipeline on that noise, not real-survey sensitivity.
      </PageHead>
      {api.kind === "demo" && <p className="notice" style={{ marginTop: 16 }}>The lab needs the live API: it runs the real pipeline, and demo data has none to test. Switch off demo data in Settings.</p>}
      <form className="lab-form" onSubmit={(e) => void run(e)}>
        <label>Planted transits{num("n_trials")}</label><label>Empty controls{num("n_controls")}</label>
        <label>Seed{num("seed")}</label>
        <label>Shortest period (days){num("period_min_d")}</label><label>Longest period (days){num("period_max_d")}</label>
        <label>Shallowest dip (ppm){num("depth_min_ppm")}</label><label>Deepest dip (ppm){num("depth_max_ppm")}</label>
        <div style={{ alignSelf: "end" }}>
          <button className="btn" disabled={running || api.kind === "demo"}>{running ? "Running" : "Run experiment"}</button>
          {running && <button type="button" className="btn" style={{ marginLeft: 8 }} onClick={() => void cancel()}>Cancel</button>}
        </div>
      </form>
      <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>Each trial takes a few seconds. Up to 60 transits and 20 controls per run.</p>
      {err && <p className="notice bad" role="alert" style={{ marginTop: 14 }}>{err}</p>}
      {exp && running && (<div aria-live="polite"><div className="lab-bar" role="progressbar" aria-valuemin={0} aria-valuemax={exp.total} aria-valuenow={exp.done}>
        <i style={{ width: `${(100 * exp.done) / Math.max(exp.total, 1)}%` }} /></div>
        <p className="muted" style={{ fontSize: 13 }}>{exp.done} of {exp.total} runs done</p></div>)}
      {exp?.status === "failed" && <p className="notice bad" role="alert" style={{ marginTop: 14 }}>The experiment failed: {exp.error}</p>}
      {exp?.status === "cancelled" && <p className="notice" style={{ marginTop: 14 }}>Cancelled. Nothing was recorded.</p>}
      {r && (
        <div style={{ marginTop: 22 }}>
          <h3>Results</h3>
          <p className="prose" style={{ marginTop: 6 }}>
            Recovered {r.overall_recovery.k} of {r.n_trials} planted transits{ci(r.overall_recovery)}.
            {r.snr_at_50pct !== null ? ` Half were found from a signal-to-noise near ${r.snr_at_50pct.toFixed(0)}.` : " The pipeline never reached a 50% recovery rate in a bin with enough trials."}
            {r.snr_at_90pct !== null ? ` Nine in ten from about ${r.snr_at_90pct.toFixed(0)}.` : ""}
            {r.false_alarm ? ` With nothing planted, ${r.false_alarm.k} of ${r.false_alarm.n} noise curves still produced a candidate${ci(r.false_alarm)}.` : ""}
          </p>
          <RecoveryChart bins={r.by_snr} />
          <Table title="By signal-to-noise" bins={r.by_snr} />
          <Table title="By period" bins={r.by_period} />
          <Table title="By depth" bins={r.by_depth} />
          <p className="notice" style={{ marginTop: 16 }}>{r.noise_note}</p>
          <ul className="muted" style={{ fontSize: 13.5, marginTop: 10 }}>{r.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
          <p className="muted hash" style={{ fontSize: 12, marginTop: 8 }}>Config hash {r.config_sha256.slice(0, 16)}</p>
        </div>)}
    </section>
  );
}
