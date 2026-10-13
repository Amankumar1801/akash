import { useCallback, useMemo, useState } from "react";
import { binWindow, estimateEpoch, niceTicks, robustRange, type Series } from "../lib/lc";
import { CanvasPlot, type Draw } from "./CanvasPlot";

const PAD = { l: 52, r: 12, t: 12, b: 34 };

function axes(ctx: CanvasRenderingContext2D, w: number, h: number, c: { ink3: string; soft: string; rule: string },
  xr: [number, number], yr: [number, number], xfmt: (v: number) => string, yfmt: (v: number) => string) {
  const X = (v: number) => PAD.l + ((v - xr[0]) / (xr[1] - xr[0])) * (w - PAD.l - PAD.r);
  const Y = (v: number) => PAD.t + (1 - (v - yr[0]) / (yr[1] - yr[0])) * (h - PAD.t - PAD.b);
  ctx.font = "11.5px 'Bricolage Grotesque Variable', system-ui, sans-serif";
  ctx.fillStyle = c.ink3; ctx.strokeStyle = c.soft; ctx.lineWidth = 1;
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (const v of niceTicks(yr[0], yr[1], 4)) {
    ctx.beginPath(); ctx.moveTo(PAD.l, Y(v) + .5); ctx.lineTo(w - PAD.r, Y(v) + .5); ctx.stroke();
    ctx.fillText(yfmt(v), PAD.l - 8, Y(v));
  }
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (const v of niceTicks(xr[0], xr[1], 6)) ctx.fillText(xfmt(v), X(v), h - PAD.b + 8);
  return { X, Y };
}
const ppm = (v: number) => `${Math.round((v - 1) * 1e6).toLocaleString("en-US")}`;

export function LightCurvePlot({ series, period, t0, durationH }: {
  series: Series; period: number | null; t0: number; durationH: number }) {
  const [hx, setHx] = useState<number | null>(null);
  const [width, setWidth] = useState(0);
  const tmin = series.t[0] ?? 0, tmax = series.t[series.t.length - 1] ?? 1;
  const yr = useMemo(() => robustRange(series.f), [series]);
  const draw = useCallback<Draw>((ctx, w, h, c, hover) => {
    const { X, Y } = axes(ctx, w, h, c, [0, tmax - tmin], yr, (v) => `${v.toFixed(0)}`, ppm);
    if (period) { // predicted dip windows
      ctx.fillStyle = c.lamp; ctx.globalAlpha = 0.16;
      const wd = Math.max(2, X(durationH / 24) - X(0));
      for (let t = t0 - Math.ceil((t0 - tmin) / period) * period; t <= tmax; t += period)
        if (t >= tmin - period) ctx.fillRect(X(t - tmin) - wd / 2, PAD.t, wd, h - PAD.t - PAD.b);
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = c.ink2; ctx.globalAlpha = 0.75;
    for (let i = 0; i < series.t.length; i++) {
      const y = series.f[i];
      if (y < yr[0] || y > yr[1]) continue;
      ctx.fillRect(X(series.t[i] - tmin) - 0.6, Y(y) - 0.6, 1.5, 1.5);
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = c.ink3; ctx.textAlign = "right"; ctx.textBaseline = "alphabetic";
    ctx.fillText("days since start", w - PAD.r, h - 2);
    if (hover !== null && hover >= PAD.l && hover <= w - PAD.r) {
      ctx.strokeStyle = c.ink3; ctx.beginPath(); ctx.moveTo(hover + .5, PAD.t); ctx.lineTo(hover + .5, h - PAD.b); ctx.stroke();
    }
  }, [series, period, t0, durationH, tmin, tmax, yr]);

  const readout = useMemo(() => {
    if (hx === null || !series.t.length || width <= PAD.l + PAD.r) return "";
    const day = ((hx - PAD.l) / (width - PAD.l - PAD.r)) * (tmax - tmin);
    if (day < 0 || day > tmax - tmin) return "";
    let lo = 0, hi = series.t.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (series.t[m] - tmin < day) lo = m + 1; else hi = m; }
    return `day ${(series.t[lo] - tmin).toFixed(2)}, ${ppm(series.f[lo])} ppm`;
  }, [hx, width, series, tmin, tmax]);
  return (
    <figure className="plot" style={{ margin: 0 }}>
      <h3>Light curve</h3>
      <p className="cap">Brightness against time, in parts per million from the median.{period ? " Amber bands mark where the search predicts dips." : ""}</p>
      <div className="frame" ref={(el) => { if (el && el.clientWidth !== width) setWidth(el.clientWidth); }}>
        <CanvasPlot draw={draw} label="Light curve of relative brightness over time" onHover={setHx} />
        {readout && <span className="readout">{readout}</span>}
      </div>
    </figure>
  );
}

export function FoldPlot({ series, period, durationH, t0 }: {
  series: Series; period: number; durationH: number; t0: number }) {
  const half = Math.min(period / 2, Math.max(durationH / 24 * 3, 4 / 24));
  const win = useMemo(() => binWindow(series, period, t0, half, 44), [series, period, t0, half]);
  const yr = useMemo(() => robustRange([...win.y, ...win.by], 0.25), [win]);
  const draw = useCallback<Draw>((ctx, w, h, c) => {
    const { X, Y } = axes(ctx, w, h, c, [-half * 24, half * 24], yr, (v) => `${v.toFixed(0)}`, ppm);
    ctx.fillStyle = c.lamp; ctx.globalAlpha = 0.14;
    ctx.fillRect(X(-durationH / 2), PAD.t, X(durationH / 2) - X(-durationH / 2), h - PAD.t - PAD.b);
    ctx.globalAlpha = 0.5; ctx.fillStyle = c.ink2;
    for (let i = 0; i < win.x.length; i++) {
      const y = win.y[i];
      if (y >= yr[0] && y <= yr[1]) ctx.fillRect(X(win.x[i] * 24) - 0.6, Y(y) - 0.6, 1.5, 1.5);
    }
    ctx.globalAlpha = 1; ctx.strokeStyle = c.lamp; ctx.lineWidth = 2; ctx.beginPath();
    win.bx.forEach((x, i) => (i ? ctx.lineTo(X(x * 24), Y(win.by[i])) : ctx.moveTo(X(x * 24), Y(win.by[i]))));
    ctx.stroke(); ctx.lineWidth = 1;
    ctx.fillStyle = c.ink3; ctx.textAlign = "right"; ctx.textBaseline = "alphabetic";
    ctx.fillText("hours from mid-transit", w - PAD.r, h - 2);
  }, [win, yr, half, durationH]);
  return (
    <figure className="plot" style={{ margin: 0 }}>
      <h3>Folded on the period</h3>
      <p className="cap">Every dip stacked on top of the others. The line averages bins of points.</p>
      <div className="frame"><CanvasPlot draw={draw} label="Light curve folded on the detected period" /></div>
    </figure>
  );
}

export const useEpoch = (series: Series, period: number | null): number =>
  useMemo(() => (period ? estimateEpoch(series, period) : 0), [series, period]);
