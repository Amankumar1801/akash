import { useEffect, useRef } from "react";
import { rng } from "../api/demo";
import { cssVar, useThemeTick } from "../lib/useTheme";

/**
 * A sparse field of stars with one that dips every few seconds: the whole product in one image.
 * Static when the visitor prefers reduced motion.
 */
export function Sky() {
  const ref = useRef<HTMLCanvasElement>(null);
  const tick = useThemeTick();
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, alive = true;
    const stars = (() => {
      const r = rng(7), out: { x: number; y: number; s: number; a: number }[] = [];
      for (let i = 0; i < 150; i++) out.push({ x: r(), y: r(), s: 0.4 + r() * 1.3, a: 0.25 + r() * 0.6 });
      return out;
    })();
    const render = (time: number) => {
      const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
      const ctx = cv.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const ink = cssVar("--ink"), lamp = cssVar("--lamp");
      ctx.fillStyle = ink;
      for (const s of stars) { ctx.globalAlpha = s.a; ctx.beginPath(); ctx.arc(s.x * r.width, s.y * r.height, s.s, 0, 7); ctx.fill(); }
      // the target star: dims for ~0.9 s of every 7 s, like a transit
      const cx = r.width * 0.80, cy = r.height * 0.34, ph = (time / 1000) % 7;
      const dip = ph > 2.4 && ph < 3.3 ? Math.sin(((ph - 2.4) / 0.9) * Math.PI) : 0;
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, 46);
      g.addColorStop(0, lamp); g.addColorStop(1, "transparent");
      ctx.globalAlpha = 0.34 * (1 - 0.55 * dip); ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(cx, cy, 46, 0, 7); ctx.fill();
      ctx.globalAlpha = 1 - 0.55 * dip; ctx.fillStyle = lamp;
      ctx.beginPath(); ctx.arc(cx, cy, 4.2, 0, 7); ctx.fill();
      ctx.globalAlpha = 1;
      if (!reduce && alive) raf = requestAnimationFrame(render);
    };
    render(0);
    const ro = new ResizeObserver(() => render(performance.now()));
    ro.observe(cv);
    return () => { alive = false; cancelAnimationFrame(raf); ro.disconnect(); };
  }, [tick]);
  return <canvas ref={ref} className="sky" aria-hidden="true" />;
}
