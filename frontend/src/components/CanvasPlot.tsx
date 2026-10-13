import { useEffect, useRef } from "react";
import { cssVar, useThemeTick } from "../lib/useTheme";

export interface Colors { ink: string; ink2: string; ink3: string; rule: string; soft: string; lamp: string; night: string; supports: string }
export type Draw = (ctx: CanvasRenderingContext2D, w: number, h: number, c: Colors, hover: number | null) => void;

/** A DPR-aware canvas that redraws on resize, theme change and hover. `hover` is the x pixel. */
export function CanvasPlot({ draw, label, onHover }: {
  draw: Draw; label: string; onHover?: (x: number | null) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const hover = useRef<number | null>(null);
  const tick = useThemeTick();
  const paint = useRef<() => void>(() => undefined);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    paint.current = () => {
      const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      if (!r.width || !r.height) return;
      cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
      const ctx = cv.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, r.width, r.height);
      draw(ctx, r.width, r.height, {
        ink: cssVar("--ink"), ink2: cssVar("--ink-2"), ink3: cssVar("--ink-3"), rule: cssVar("--rule"),
        soft: cssVar("--rule-soft"), lamp: cssVar("--lamp"), night: cssVar("--night"),
        supports: cssVar("--supports") }, hover.current);
    };
    paint.current();
    const ro = new ResizeObserver(() => paint.current());
    ro.observe(cv);
    return () => ro.disconnect();
  }, [draw, tick]);

  return (
    <canvas ref={ref} role="img" aria-label={label}
      onPointerMove={(e) => { const r = e.currentTarget.getBoundingClientRect();
        hover.current = e.clientX - r.left; onHover?.(hover.current); paint.current(); }}
      onPointerLeave={() => { hover.current = null; onHover?.(null); paint.current(); }} />
  );
}
