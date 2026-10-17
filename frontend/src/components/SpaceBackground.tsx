import { useEffect, useRef } from "react";
import { rng } from "../api/demo";
import { cssVar, useThemeTick } from "../lib/useTheme";

interface Star { x: number; y: number; r: number; a: number; tint: number; ph: number; sp: number; glint: boolean }

function field(seed: number, n: number, rmin: number, rmax: number, amin: number, amax: number, glints = 0): Star[] {
  const r = rng(seed), out: Star[] = [];
  for (let i = 0; i < n; i++) {
    out.push({ x: r(), y: r(), r: rmin + r() * (rmax - rmin), a: amin + r() * (amax - amin),
      tint: r(), ph: r() * 6.28, sp: 0.25 + r() * 0.9, glint: i < glints });
  }
  return out;
}
const FAR = field(11, 230, 0.3, 0.9, 0.18, 0.6);
const NEAR = field(23, 34, 0.7, 1.5, 0.35, 0.85, 5);

/**
 * Fixed deep-space environment behind the whole app: haze and a faint coordinate grid (CSS), a
 * static far star layer, and a sparse near layer where a few stars twinkle on long, unsynchronised
 * cycles. Positions are seeded, so they never change between renders. Pointer parallax is tiny and
 * off for touch and for reduced motion; drawing pauses when the tab is hidden and is capped at
 * ~30 fps. It never receives pointer events.
 */
export function SpaceBackground() {
  const far = useRef<HTMLCanvasElement>(null);
  const near = useRef<HTMLCanvasElement>(null);
  const tick = useThemeTick();

  useEffect(() => {
    const a = far.current, b = near.current;
    if (!a || !b) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const fine = window.matchMedia("(pointer: fine)");
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    let w = 0, h = 0, raf = 0, last = 0, px = 0, py = 0, cx = 0, cy = 0;
    const ink = cssVar("--ink"), lamp = cssVar("--lamp"), cool = cssVar("--supports");
    const size = () => {
      w = window.innerWidth + 60; h = window.innerHeight + 60;
      for (const c of [a, b]) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); c.style.width = `${w}px`; c.style.height = `${h}px`; }
    };
    const dot = (ctx: CanvasRenderingContext2D, s: Star, alpha: number) => {
      ctx.globalAlpha = alpha;
      ctx.fillStyle = s.tint > 0.93 ? lamp : s.tint < 0.12 ? cool : ink;
      ctx.beginPath(); ctx.arc(s.x * w, s.y * h, s.r, 0, 7); ctx.fill();
    };
    const drawFar = () => {
      const ctx = a.getContext("2d"); if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      for (const s of FAR) dot(ctx, s, s.a);
      ctx.globalAlpha = 1;
    };
    const drawNear = (t: number, animate: boolean) => {
      const ctx = b.getContext("2d"); if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      for (const s of NEAR) {
        const k = animate ? 0.55 + 0.45 * Math.sin(t * 0.001 * s.sp + s.ph) : 1;
        dot(ctx, s, s.a * (s.ph > 4.2 || s.glint ? k : 1));
        if (s.glint) {  // a faint diffraction cross on the brightest few
          ctx.globalAlpha = 0.22 * k; ctx.strokeStyle = ink; ctx.lineWidth = 0.6; ctx.beginPath();
          ctx.moveTo(s.x * w - 6, s.y * h); ctx.lineTo(s.x * w + 6, s.y * h);
          ctx.moveTo(s.x * w, s.y * h - 6); ctx.lineTo(s.x * w, s.y * h + 6); ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    };
    const move = (e: PointerEvent) => { px = (e.clientX / window.innerWidth - 0.5) * 2; py = (e.clientY / window.innerHeight - 0.5) * 2; };
    const loop = (t: number) => {
      raf = requestAnimationFrame(loop);
      if (document.hidden || t - last < 33) return;
      last = t;
      drawNear(t, true);
      cx += (px - cx) * 0.06; cy += (py - cy) * 0.06;  // eased, a few pixels at most
      a.style.transform = `translate3d(${(-cx * 4 - 30).toFixed(2)}px, ${(-cy * 4 - 30).toFixed(2)}px, 0)`;
      b.style.transform = `translate3d(${(-cx * 10 - 30).toFixed(2)}px, ${(-cy * 10 - 30).toFixed(2)}px, 0)`;
    };
    const start = () => {
      cancelAnimationFrame(raf);
      size(); drawFar(); drawNear(0, false);
      a.style.transform = b.style.transform = "translate3d(-30px, -30px, 0)";
      if (!reduce.matches) raf = requestAnimationFrame(loop);
    };
    start();
    const onResize = () => start();
    window.addEventListener("resize", onResize);
    reduce.addEventListener("change", start);
    if (fine.matches) window.addEventListener("pointermove", move, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", move);
      reduce.removeEventListener("change", start);
    };
  }, [tick]);

  return (
    <div className="space" aria-hidden="true">
      <div className="space-haze" />
      <div className="space-grid" />
      <canvas ref={far} className="space-far" />
      <canvas ref={near} className="space-near" />
    </div>
  );
}
