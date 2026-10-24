import { useEffect, useMemo, useRef, useState } from "react";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import sample from "../api/spectrum_sample.json";
import type { SpectrumResult } from "../api/types";
import { parseSpectrumCsv } from "../lib/spectrumCsv";
import { cssVar, useThemeTick } from "../lib/useTheme";
import { Spinner } from "../components/Loader";
import { PageHead } from "../components/PageHead";
import { Scene } from "../components/Scene";

const STATUS: Record<SpectrumResult["redshift"]["status"], string> = {
  no_lines: "No lines strong enough to test",
  single_line_only: "One strong line, which cannot fix a redshift",
  no_match: "Lines found, no redshift explains them",
  candidate_redshift: "Candidate redshift",
  ambiguous: "More than one redshift fits",
};
const MAX_FILE = 2_000_000;

function SpectrumPlot({ w, f, res }: { w: number[]; f: (number | null)[]; res: SpectrumResult | null }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const last = useRef<{ w?: unknown; f?: unknown; res?: unknown }>({});
  const tick = useThemeTick();
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    // t runs 0..1 once per new spectrum/result: axes fade in, the actual trace is revealed left to
    // right by clipping (no data is recomputed), then the detected lines appear. Repaints for resize
    // or theme use t = 1.
    const paint = (t = 1) => {
      const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
      const ctx = cv.getContext("2d");
      if (!ctx || !w.length) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const W = r.width, H = r.height, L = 46, R = 12, T = 18, B = 30;
      const ys = f.filter((v): v is number => v !== null);
      const lo = Math.min(...ys), hi = Math.max(...ys), pad = (hi - lo) * 0.06 || 1;
      const x0 = w[0], x1 = w[w.length - 1];
      const X = (x: number) => L + ((x - x0) / (x1 - x0)) * (W - L - R);
      const Y = (y: number) => H - B - ((y - (lo - pad)) / (hi - lo + 2 * pad)) * (H - T - B);
      ctx.globalAlpha = Math.min(1, t * 3);
      ctx.strokeStyle = cssVar("--rule-soft"); ctx.fillStyle = cssVar("--ink-3"); ctx.font = "11px system-ui"; ctx.lineWidth = 1;
      for (let i = 0; i <= 5; i++) {
        const x = x0 + ((x1 - x0) * i) / 5;
        ctx.beginPath(); ctx.moveTo(X(x), T); ctx.lineTo(X(x), H - B); ctx.stroke();
        ctx.fillText(`${Math.round(x)}`, X(x) - (i === 5 ? 26 : 12), H - 12);
      }
      ctx.fillText("Wavelength (Angstrom)", W / 2 - 50, H - 1);
      ctx.globalAlpha = 1;
      const p = Math.min(1, t / 0.75);
      const sweepX = L + p * (W - L - R);
      if (res) {
        const best = res.redshift.candidates[0];
        const matched = new Map(best?.matched_lines.map((m) => [m.observed_a, m.rest]) ?? []);
        let k = 0;
        for (const ln of res.lines) {
          const x = X(ln.wavelength_a);
          if (x > sweepX) continue;                        // a line appears only once the sweep has passed it
          const age = p >= 1 ? 1 : Math.min(1, (sweepX - x) / 90);
          const flash = 1 - Math.min(1, age * 1.6);       // a brief bright flash as the sweep crosses
          const col = cssVar(ln.kind === "emission" ? "--supports" : "--warn");
          if (flash > 0) {
            ctx.globalAlpha = flash * 0.5; ctx.fillStyle = col; ctx.fillRect(x - 5, T, 10, H - T - B);
          }
          ctx.globalAlpha = Math.min(1, 0.35 + age); ctx.strokeStyle = col;
          ctx.setLineDash([3, 3]);
          ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, H - B); ctx.stroke();
          ctx.setLineDash([]);
          const name = matched.get(ln.wavelength_a);
          if (name) {
            ctx.globalAlpha = Math.min(1, age * 1.4); ctx.fillStyle = cssVar("--ink");
            ctx.fillText(name, Math.min(x + 3, W - 70), T + 8 + (k++ % 4) * 12);
          }
        }
        ctx.globalAlpha = 1;
      }
      if (p < 1) {   // the scanning cursor
        const g = ctx.createLinearGradient(sweepX - 30, 0, sweepX, 0);
        g.addColorStop(0, "transparent"); g.addColorStop(1, cssVar("--lamp"));
        ctx.globalAlpha = 0.22; ctx.fillStyle = g; ctx.fillRect(sweepX - 30, T, 30, H - T - B);
        ctx.globalAlpha = 0.9; ctx.fillStyle = cssVar("--lamp"); ctx.fillRect(sweepX, T, 1.2, H - T - B);
        ctx.globalAlpha = 1;
      }
      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, p >= 1 ? W : L + p * (W - L - R), H); ctx.clip();
      ctx.strokeStyle = cssVar("--ink"); ctx.lineWidth = 1.2; ctx.beginPath();
      let pen = false;
      w.forEach((x, i) => {
        const y = f[i];
        if (y === null) { pen = false; return; }
        if (!pen) { ctx.moveTo(X(x), Y(y)); pen = true; } else ctx.lineTo(X(x), Y(y));
      });
      ctx.stroke();
      ctx.restore();
    };
    const same = last.current.w === w && last.current.f === f && last.current.res === res;
    last.current = { w, f, res };
    const still = same || window.matchMedia("(prefers-reduced-motion: reduce)").matches || w.length > 20000;
    let raf = 0, animating = !still;
    if (still) paint(1);
    else {
      const t0 = performance.now();
      const step = (now: number) => {
        const t = Math.min(1, (now - t0) / (res ? 1900 : 1000));
        paint(t);                  // a steady sweep, so lines flash at a constant pace
        if (t < 1) raf = requestAnimationFrame(step); else animating = false;
      };
      raf = requestAnimationFrame(step);
    }
    const ro = new ResizeObserver(() => { if (!animating) paint(1); }); ro.observe(cv);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, [w, f, res, tick]);
  const [tip, setTip] = useState<{ x: number; text: string } | null>(null);
  const near = (e: React.PointerEvent<HTMLCanvasElement>) => {   // the nearest detected line within a few pixels
    if (!res || !w.length) return;
    const r = e.currentTarget.getBoundingClientRect(), L = 46, R = 12, x0 = w[0], x1 = w[w.length - 1];
    const mx = e.clientX - r.left;
    let best: { x: number; text: string } | null = null, d = 7;
    for (const ln of res.lines) {
      const x = L + ((ln.wavelength_a - x0) / (x1 - x0)) * (r.width - L - R);
      if (Math.abs(x - mx) < d) {
        d = Math.abs(x - mx);
        best = { x, text: `${ln.kind === "emission" ? "Emission" : "Absorption"} line at ${ln.wavelength_a.toFixed(1)} Å${ln.matched ? `, matched to ${ln.matched}` : ", no catalogue match"}` };
      }
    }
    setTip(best);
  };
  return (
    <div className="spec-wrap">
      <canvas ref={ref} className="spec-plot" role="img" onPointerMove={near} onPointerLeave={() => setTip(null)}
        aria-label={`Spectrum from ${w[0]?.toFixed(0)} to ${w[w.length - 1]?.toFixed(0)} Angstrom with ${res?.lines.length ?? 0} detected lines. The line table follows.`} />
      {tip && <span className="spec-tip" style={{ left: tip.x }}>{tip.text}</span>}
    </div>
  );
}

export function Spectra() {
  const { api } = useApi();
  const [text, setText] = useState("");
  const [data, setData] = useState<{ w: number[]; f: (number | null)[]; e: (number | null)[] | null } | null>(null);
  const [res, setRes] = useState<SpectrumResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState("");

  const useSample = () => {
    setText(sample.wavelength_a.map((x, i) => `${x},${sample.flux[i]}`).join("\n"));
    setLabel("synthetic sample"); setRes(null); setErr(null);
  };
  const onFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_FILE) { setErr("That file is over 2 MB. A spectrum of 20,000 rows is smaller than that."); return; }
    setText(await file.text()); setLabel(file.name.slice(0, 80)); setRes(null); setErr(null);
  };
  const parsed = useMemo(() => (text.trim() ? parseSpectrumCsv(text) : null), [text]);
  useEffect(() => {
    if (parsed && typeof parsed !== "string") setData({ w: parsed.wavelength_a, f: parsed.flux, e: parsed.flux_err });
    else setData(null);
  }, [parsed]);

  const analyze = async () => {
    if (!parsed || typeof parsed === "string") return;
    setBusy(true); setErr(null);
    try { setRes(await api.analyzeSpectrum({ wavelength_a: parsed.wavelength_a, flux: parsed.flux, flux_err: parsed.flux_err, label: label || undefined })); }
    catch (e) { setErr(explain(e)); setRes(null); } finally { setBusy(false); }
  };

  const z = res?.redshift;
  return (
    <section className="section">
      <Scene name="sky" />
      <PageHead eyebrow="Spectra" title="See the light" accent="in more detail.">
        Paste or upload a one-dimensional spectrum. AKASH finds emission and absorption lines and checks whether one redshift makes
        several of them match known lines. A redshift here is a candidate with its supporting lines, never a confirmed value,
        and nothing here classifies the object.
      </PageHead>
      <div className="spec-input">
        <label>Spectrum, one row per pixel: wavelength (Angstrom), flux, optional error
          <textarea value={text} rows={6} spellCheck={false} placeholder={"4000, 10.1\n4004, 10.0\n..."}
                    onChange={(e) => { setText(e.target.value); setRes(null); setLabel(""); }} /></label>
        <div className="spec-actions">
          <label className="btn">Upload a file
            <input type="file" accept=".csv,.txt,.dat,text/plain,text/csv" hidden onChange={(e) => void onFile(e.target.files?.[0])} /></label>
          <button className="btn" onClick={useSample}>Use the synthetic sample</button>
          <button className="btn primary" onClick={() => void analyze()} disabled={busy || !parsed || typeof parsed === "string"}>
            {busy ? <><Spinner />Analysing</> : "Analyse"}</button>
        </div>
        {typeof parsed === "string" && <p className="notice bad" role="alert">{parsed}</p>}
        {err && <p className="notice bad" role="alert">{err}</p>}
      </div>

      {data && <SpectrumPlot w={data.w} f={data.f} res={res} />}

      {res && z && (
        <div style={{ marginTop: 18 }}>
          {res.precomputed && <p className="muted" style={{ fontSize: 13.5 }}>Demo mode: this analysis was computed ahead of time by the Python code on the synthetic sample.</p>}
          <h3 style={{ margin: "6px 0" }}>{STATUS[z.status]}{z.tier ? ` (${z.tier})` : ""}</h3>
          <p className="prose" style={{ marginTop: 0 }}>{z.note}</p>
          {z.candidates.length > 0 && (
            <div className="scroll-x"><table className="tbl">
              <thead><tr><th>Redshift z</th><th>Lines matched</th><th>Scatter (km/s)</th><th>Which lines</th></tr></thead>
              <tbody>{z.candidates.map((c, i) => (
                <tr key={i} style={{ cursor: "default" }}><td className="num"><b>{c.z.toFixed(4)}</b></td><td className="num">{c.n_matched}</td>
                  <td className="num">{c.z_scatter_kms.toFixed(0)}</td><td>{c.matched_lines.map((m) => m.rest).join(", ")}</td></tr>))}</tbody>
            </table></div>)}
          {res.broad_emission.length > 0 && <p className="notice" style={{ marginTop: 12 }}>
            Broad emission (wider than 1,000 km/s): {res.broad_emission.join(", ")}. Several kinds of object show this, so it is a description, not a classification.</p>}
          <h3 style={{ margin: "18px 0 6px" }}>Detected lines ({res.lines.length})</h3>
          {res.lines.length === 0 ? <p className="empty">No lines stood out from the noise.</p> : (
            <div className="scroll-x"><table className="tbl">
              <thead><tr><th>Wavelength (A)</th><th>Type</th><th>Significance</th><th>Equivalent width (A)</th><th>Width (km/s)</th><th>Matches</th></tr></thead>
              <tbody>{res.lines.map((l, i) => (
                <tr key={i} style={{ cursor: "default" }}><td className="num">{l.wavelength_a.toFixed(1)}</td><td>{l.kind}</td>
                  <td className="num">{l.snr.toFixed(1)} sigma</td><td className="num">{l.equivalent_width_a.toFixed(2)}</td>
                  <td className="num">{l.fwhm_kms === null ? "unresolved" : l.fwhm_kms.toFixed(0)}</td><td>{l.matched ?? "none"}</td></tr>))}</tbody>
            </table></div>)}
          <ul className="muted" style={{ fontSize: 13.5, marginTop: 14, paddingLeft: 18 }}>{res.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
          <p className="muted" style={{ fontSize: 13 }}>Input hash {res.input_sha256.slice(0, 16)}. Noise estimated from {res.noise_source === "flux_err" ? "your flux errors" : "the scatter of the spectrum"}.</p>
        </div>
      )}
    </section>
  );
}
