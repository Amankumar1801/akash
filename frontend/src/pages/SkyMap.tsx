import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { SkyOut, SkyPoint } from "../api/types";
import { TRIAGE } from "../lib/labels";
import { nearest, project, toPixel, X_MAX, Y_MAX } from "../lib/sky";
import { cssVar, useThemeTick } from "../lib/useTheme";
import { PageHead } from "../components/PageHead";

const TONE_VAR = { supports: "--supports", contradicts: "--rose", inconclusive: "--ink-2", neutral: "--ink-3" } as const;
const color = (cat: SkyPoint["category"]) => cssVar(TONE_VAR[TRIAGE[cat].tone]) || cssVar("--lamp");

export function SkyMap() {
  const { api } = useApi();
  const [sky, setSky] = useState<SkyOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<number>(-1);
  const [hov, setHov] = useState<number>(-1);
  const ref = useRef<HTMLCanvasElement>(null);
  const tick = useThemeTick();
  const pts = useMemo(() => sky?.points ?? [], [sky]);

  useEffect(() => {
    let live = true;
    api.sky().then((s) => live && setSky(s)).catch((e) => live && setErr(explain(e)));
    return () => { live = false; };
  }, [api]);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const paint = () => {
      const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
      const ctx = cv.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const w = r.width, h = r.height, { scale } = toPixel(0, 0, w, h);
      ctx.strokeStyle = cssVar("--rule"); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.ellipse(w / 2, h / 2, X_MAX * scale, Y_MAX * scale, 0, 0, 7); ctx.stroke();
      ctx.strokeStyle = cssVar("--rule-soft");
      for (let ra = 0; ra < 360; ra += 30) {            // meridians
        ctx.beginPath();
        for (let d = -90; d <= 90; d += 3) { const p = toPixel(ra === 0 ? 0.001 : ra, d, w, h); d === -90 ? ctx.moveTo(p.px, p.py) : ctx.lineTo(p.px, p.py); }
        ctx.stroke();
      }
      for (let d = -60; d <= 60; d += 30) {             // parallels
        ctx.beginPath();
        for (let ra = 0; ra <= 360; ra += 3) { const p = toPixel(ra === 360 ? 359.999 : ra, d, w, h); ra === 0 ? ctx.moveTo(p.px, p.py) : ctx.lineTo(p.px, p.py); }
        ctx.stroke();
      }
      ctx.fillStyle = cssVar("--ink-3"); ctx.font = "11px system-ui";
      for (const ra of [0, 90, 180, 270]) { const p = toPixel(ra, 0, w, h); ctx.fillText(`${ra}°`, p.px + 3, p.py - 3); }
      pts.forEach((p, i) => {
        const { px, py } = toPixel(p.ra_deg, p.dec_deg, w, h);
        ctx.fillStyle = color(p.category);
        ctx.beginPath(); ctx.arc(px, py, i === sel || i === hov ? 6 : 3.6, 0, 7); ctx.fill();
        if (i === sel) { ctx.strokeStyle = cssVar("--ink"); ctx.lineWidth = 1.5; ctx.stroke(); }
      });
    };
    paint();
    const ro = new ResizeObserver(paint); ro.observe(cv);
    return () => ro.disconnect();
  }, [pts, sel, hov, tick]);

  const at = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return nearest(pts, e.clientX - r.left, e.clientY - r.top, r.width, r.height);
  };
  const p = sel >= 0 ? pts[sel] : null;
  void project;

  return (
    <section className="section">
      <PageHead eyebrow="Sky" title="Explore the sky" accent="of your investigations.">
        Where the objects you have investigated sit on the sky (Hammer-Aitoff projection, right ascension increasing to the left).
        {" "}{sky?.note}
      </PageHead>
      {err && <p className="notice bad" role="alert" style={{ marginTop: 14 }}>{err}</p>}
      <div className="sky-wrap">
        <canvas ref={ref} className="sky-map" role="img" aria-label={`All-sky map with ${pts.length} investigated objects. A list of the same objects follows.`}
                onMouseMove={(e) => setHov(at(e))} onMouseLeave={() => setHov(-1)} onClick={(e) => setSel(at(e))} />
        <aside className="sky-side" aria-live="polite">
          {hov >= 0 && sel < 0 && <p className="muted">{pts[hov].name}</p>}
          {p ? (<>
            <h3>{p.name}</h3>
            <p className="muted">{TRIAGE[p.category].title}</p>
            <p className="num">RA {p.ra_deg.toFixed(3)}, Dec {p.dec_deg.toFixed(3)}</p>
            {p.anomaly_percentile !== null && <p className="num">Anomaly percentile {Math.round(p.anomaly_percentile)}</p>}
            <Link className="btn" to={`/investigations/${p.investigation_id}`}>Investigate with AKASH</Link>
          </>) : <p className="muted">Click an object to see it. Colour follows the triage category, not a rating.</p>}
        </aside>
      </div>
      {sky && sky.n === 0 && <p className="empty">No investigated objects yet. Run an investigation from the logbook and it will appear here.</p>}
      {pts.length > 0 && (
        <details style={{ marginTop: 18 }}><summary>List of the {pts.length} objects on this map</summary>
          <ul className="sky-list">{pts.map((q, i) => (
            <li key={q.investigation_id}><button className="linkish" onClick={() => setSel(i)}>{q.name}</button> <span className="muted">{TRIAGE[q.category].title}</span></li>))}</ul>
        </details>)}
    </section>
  );
}
