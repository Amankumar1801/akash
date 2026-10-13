// Light-curve helpers for plotting. These are display aids, not pipeline science.
export interface Series { t: number[]; f: number[] }

/** Min/max envelope downsampling: keeps every dip and spike that a stride would drop. */
export function minmaxIndices(y: ArrayLike<number>, maxPoints: number): number[] {
  const n = y.length;
  if (n <= maxPoints) return Array.from({ length: n }, (_, i) => i);
  const buckets = Math.max(1, Math.floor(maxPoints / 2));
  const out: number[] = [];
  for (let b = 0; b < buckets; b++) {
    const lo = Math.floor((b * n) / buckets), hi = Math.floor(((b + 1) * n) / buckets);
    if (hi <= lo) continue;
    let imin = lo, imax = lo;
    for (let i = lo; i < hi; i++) { if (y[i] < y[imin]) imin = i; if (y[i] > y[imax]) imax = i; }
    if (imin === imax) out.push(imin);
    else out.push(Math.min(imin, imax), Math.max(imin, imax));
  }
  return out;
}

export function median(a: number[]): number {
  if (!a.length) return NaN;
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** Drop flagged/null samples and divide by the median so depth reads in parts per million. */
export function cleanSeries(time: number[], flux: (number | null)[], flagged: boolean[]): Series {
  const t: number[] = [], f: number[] = [];
  for (let i = 0; i < time.length; i++) {
    const v = flux[i];
    if (v === null || v === undefined || !Number.isFinite(v) || flagged[i]) continue;
    t.push(time[i]); f.push(v);
  }
  const m = median(f) || 1;
  return { t, f: f.map((v) => v / m) };
}

export const phaseOf = (t: number, period: number, t0: number): number => {
  const p = ((t - t0) / period + 0.5) % 1;
  return (p < 0 ? p + 1 : p) - 0.5; // in [-0.5, 0.5), transit at 0
};

export interface Binned { phase: number[]; flux: number[]; n: number[] }
export function binFold(s: Series, period: number, t0: number, nbins: number): Binned {
  const sum = new Float64Array(nbins), cnt = new Uint32Array(nbins);
  for (let i = 0; i < s.t.length; i++) {
    const b = Math.min(nbins - 1, Math.floor((phaseOf(s.t[i], period, t0) + 0.5) * nbins));
    sum[b] += s.f[i]; cnt[b]++;
  }
  const phase: number[] = [], flux: number[] = [], n: number[] = [];
  for (let b = 0; b < nbins; b++) {
    if (!cnt[b]) continue;
    phase.push((b + 0.5) / nbins - 0.5); flux.push(sum[b] / cnt[b]); n.push(cnt[b]);
  }
  return { phase, flux, n };
}

/**
 * Pick a display epoch: the phase shift whose binned fold is deepest. The API reports period,
 * depth and duration but not the epoch, so this exists only to centre the fold on screen.
 */
export function estimateEpoch(s: Series, period: number, nShifts = 120): number {
  if (!s.t.length) return 0;
  const tmin = s.t[0];
  let best = tmin, bestDepth = Infinity;
  for (let k = 0; k < nShifts; k++) {
    const t0 = tmin + (k / nShifts) * period;
    const b = binFold(s, period, t0, 60);
    const centre = b.flux.filter((_, i) => Math.abs(b.phase[i]) < 0.04);
    if (!centre.length) continue;
    const m = centre.reduce((a, c) => a + c, 0) / centre.length;
    if (m < bestDepth) { bestDepth = m; best = t0; }
  }
  return best;
}

export function extent(a: ArrayLike<number>): [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < a.length; i++) { if (a[i] < lo) lo = a[i]; if (a[i] > hi) hi = a[i]; }
  return [lo, hi];
}

/** Robust y-range for plotting: clip to the 0.5/99.5 percentiles, then pad. */
export function robustRange(f: number[], pad = 0.15): [number, number] {
  if (!f.length) return [0.99, 1.01];
  const s = [...f].sort((a, b) => a - b);
  const lo = s[Math.floor(s.length * 0.003)], hi = s[Math.ceil(s.length * 0.997) - 1];
  const span = Math.max(hi - lo, 1e-6);
  return [lo - span * pad, hi + span * pad];
}

/** Bin points within +/- halfWidth days of mid-transit; x is in days from mid-transit. */
export function binWindow(s: Series, period: number, t0: number, halfWidth: number, nbins: number) {
  const sum = new Float64Array(nbins), cnt = new Uint32Array(nbins);
  const x: number[] = [], y: number[] = [];
  for (let i = 0; i < s.t.length; i++) {
    const dx = phaseOf(s.t[i], period, t0) * period;
    if (Math.abs(dx) > halfWidth) continue;
    x.push(dx); y.push(s.f[i]);
    const b = Math.min(nbins - 1, Math.floor(((dx + halfWidth) / (2 * halfWidth)) * nbins));
    sum[b] += s.f[i]; cnt[b]++;
  }
  const bx: number[] = [], by: number[] = [];
  for (let b = 0; b < nbins; b++) if (cnt[b]) { bx.push(-halfWidth + ((b + 0.5) / nbins) * 2 * halfWidth); by.push(sum[b] / cnt[b]); }
  return { x, y, bx, by };
}

export function niceTicks(lo: number, hi: number, target = 5): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / target, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}
