import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { SkyOut, SkyPoint } from "../api/types";
import { TRIAGE } from "../lib/labels";
import { nearest, project, toPixel, X_MAX, Y_MAX } from "../lib/sky";
import { cssVar, useThemeTick } from "../lib/useTheme";
import { PageHead } from "../components/PageHead";
import { Scene } from "../components/Scene";

const TONE_VAR = { supports: "--supports", contradicts: "--rose", inconclusive: "--ink-2", neutral: "--ink-3" } as const;
const color = (cat: SkyPoint["category"]) => cssVar(TONE_VAR[TRIAGE[cat].tone]) || cssVar("--lamp");

export function SkyMap() {
  const { api } = useApi();
  const [sky, setSky] = useState<SkyOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<number>(-1);
  const [hov, setHov] = useState<number>(-1);
  const ref = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const link = useRef<HTMLAnchorElement>(null);
  const nav = useNavigate();
  const [fly, setFly] = useState<{ ox: number; oy: number; arc: string } | null>(null);   // the dive towards the chosen star
  const [dip, setDip] = useState<{ ox: number; oy: number } | null>(null);              // the short zoom-and-tilt on selection
  const tick = useThemeTick();
  // Animation clocks live in refs, so hover and reveal never re-render React.
  const gridT = useRef(0), ptsT = useRef(0), selAt = useRef(-1e9);
  const repaint = useRef<() => void>(() => undefined);
  const calm = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const run = (ms: number, set: (t: number) => void) => {
    if (calm()) { set(1); repaint.current(); return () => undefined; }
    let raf = 0; const t0 = performance.now();
    const step = (now: number) => { const t = Math.min(1, (now - t0) / ms); set(1 - (1 - t) ** 3); repaint.current(); if (t < 1) raf = requestAnimationFrame(step); };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  };
  const pts = useMemo(() => sky?.points ?? [], [sky]);

  useEffect(() => {
    let live = true;
    api.sky().then((s) => live && setSky(s)).catch((e) => live && setErr(explain(e)));
    return () => { live = false; };
  }, [api]);

  useEffect(() => run(650, (t) => { gridT.current = t; }), []);               // grid fades in on first view
  useEffect(() => (pts.length ? run(900, (t) => { ptsT.current = t; }) : undefined), [pts]);   // real points, staggered
  useEffect(() => {
    if (sel < 0) return;
    selAt.current = performance.now();
    return run(480, () => undefined);                                       // ring expands from the selected object
  }, [sel]);

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
      ctx.globalAlpha = Math.min(1, gridT.current * 1.4);
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
      ctx.globalAlpha = 1;
      const n = Math.max(1, pts.length), now = performance.now();
      pts.forEach((p, i) => {
        const { px, py } = toPixel(p.ra_deg, p.dec_deg, w, h);
        const a = Math.max(0, Math.min(1, (ptsT.current - 0.45 * (i / n)) / 0.55));   // stagger over the real set
        if (a <= 0) return;
        const hot = i === sel || i === hov, c = color(p.category);
        ctx.globalAlpha = a;
        if (hot) {   // restrained halo
          const g = ctx.createRadialGradient(px, py, 0, px, py, 16);
          g.addColorStop(0, c); g.addColorStop(1, "transparent");
          ctx.globalAlpha = a * 0.32; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(px, py, 16, 0, 7); ctx.fill();
          ctx.globalAlpha = a;
        }
        ctx.fillStyle = c;
        ctx.beginPath(); ctx.arc(px, py, hot ? 5.6 : 3.6, 0, 7); ctx.fill();
        if (i === sel) {
          ctx.strokeStyle = cssVar("--ink"); ctx.lineWidth = 1.4;
          ctx.beginPath(); ctx.arc(px, py, 9, 0, 7); ctx.stroke();
          const k = Math.min(1, (now - selAt.current) / 480);   // one expanding ring on selection
          if (k < 1) { ctx.globalAlpha = (1 - k) * 0.7; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(px, py, 9 + 14 * k, 0, 7); ctx.stroke(); }
        }
        ctx.globalAlpha = 1;
      });
    };
    repaint.current = paint;
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
  const choose = (i: number) => {
    setSel(i);
    const cv = ref.current;
    if (i < 0 || !cv || calm()) return;
    const r = cv.getBoundingClientRect(), q = toPixel(pts[i].ra_deg, pts[i].dec_deg, r.width, r.height);
    setDip({ ox: q.px, oy: q.py });
    window.setTimeout(() => setDip(null), 1300);
  };
  // Opening the investigation: the map dives towards the star and an arc is drawn from it to the
  // button, then the page changes. Without motion it simply navigates.
  const dive = (e: React.MouseEvent<HTMLAnchorElement>) => {
    const cv = ref.current, wr = wrap.current, ln = link.current;
    if (!p || !cv || !wr || !ln || calm() || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    const rc = cv.getBoundingClientRect(), rw = wr.getBoundingClientRect(), rl = ln.getBoundingClientRect();
    const q = toPixel(p.ra_deg, p.dec_deg, rc.width, rc.height);
    const x0 = rc.left - rw.left + q.px, y0 = rc.top - rw.top + q.py, x1 = rl.left - rw.left + rl.width / 2, y1 = rl.top - rw.top + rl.height / 2;
    setFly({ ox: q.px, oy: q.py, arc: `M${x0.toFixed(1)} ${y0.toFixed(1)} Q${((x0 + x1) / 2).toFixed(1)} ${(Math.min(y0, y1) - 70).toFixed(1)} ${x1.toFixed(1)} ${y1.toFixed(1)}` });
    window.setTimeout(() => nav(`/investigations/${p.investigation_id}`), 720);
  };

  return (
    <section className="section">
      <Scene name="sky" />
      <PageHead eyebrow="Sky" title="Explore the sky" accent="of your investigations.">
        Where the objects you have investigated sit on the sky (Hammer-Aitoff projection, right ascension increasing to the left).
        {" "}{sky?.note}
      </PageHead>
      {err && <p className="notice bad" role="alert" style={{ marginTop: 14 }}>{err}</p>}
      <div className="sky-wrap" ref={wrap}>
        <canvas ref={ref} className={`sky-map${dip ? " dip" : ""}${fly ? " dive" : ""}`}
                style={dip || fly ? { transformOrigin: `${(fly ?? dip)!.ox}px ${(fly ?? dip)!.oy}px` } : undefined} role="img" aria-label={`All-sky map with ${pts.length} investigated objects. A list of the same objects follows.`}
                onMouseMove={(e) => setHov(at(e))} onMouseLeave={() => setHov(-1)} onClick={(e) => choose(at(e))} />
        {fly && <svg className="sky-arc" aria-hidden="true"><path d={fly.arc} pathLength={1} /></svg>}
        <aside className="sky-side" aria-live="polite">
          {hov >= 0 && sel < 0 && <p className="muted">{pts[hov].name}</p>}
          {p ? (<>
            <h3>{p.name}</h3>
            <p className="muted">{TRIAGE[p.category].title}</p>
            <p className="num">RA {p.ra_deg.toFixed(3)}, Dec {p.dec_deg.toFixed(3)}</p>
            {p.anomaly_percentile !== null && <p className="num">Anomaly percentile {Math.round(p.anomaly_percentile)}</p>}
            <Link ref={link} onClick={dive} className="btn" to={`/investigations/${p.investigation_id}`}>Investigate with AKASH</Link>
          </>) : <p className="muted">Click an object to see it. Colour follows the triage category, not a rating.</p>}
        </aside>
      </div>
      {sky && sky.n === 0 && <p className="empty">No investigated objects yet. Run an investigation from the logbook and it will appear here.</p>}
      {pts.length > 0 && (
        <details style={{ marginTop: 18 }}><summary>List of the {pts.length} objects on this map</summary>
          <ul className="sky-list">{pts.map((q, i) => (
            <li key={q.investigation_id}><button className="linkish" onClick={() => choose(i)}>{q.name}</button> <span className="muted">{TRIAGE[q.category].title}</span></li>))}</ul>
        </details>)}
    </section>
  );
}
