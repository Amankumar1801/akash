/** Hammer-Aitoff all-sky projection. RA increases to the left, as on a sky chart. */
export function project(raDeg: number, decDeg: number): { x: number; y: number } {
  const lon = ((((raDeg - 180) % 360) + 540) % 360) - 180;   // centre the map on RA 180 deg
  const l = (-lon * Math.PI) / 180, p = (decDeg * Math.PI) / 180;
  const d = Math.sqrt(1 + Math.cos(p) * Math.cos(l / 2));
  return { x: (2 * Math.SQRT2 * Math.cos(p) * Math.sin(l / 2)) / d, y: (Math.SQRT2 * Math.sin(p)) / d };
}
export const X_MAX = 2 * Math.SQRT2, Y_MAX = Math.SQRT2;

export function toPixel(raDeg: number, decDeg: number, w: number, h: number, pad = 12) {
  const { x, y } = project(raDeg, decDeg);
  const sx = (w - 2 * pad) / (2 * X_MAX), sy = (h - 2 * pad) / (2 * Y_MAX), s = Math.min(sx, sy);
  return { px: w / 2 + x * s, py: h / 2 - y * s, scale: s };
}

/** Index of the nearest point within `maxPx` pixels, or -1. Linear scan: fine up to the API's cap. */
export function nearest(pts: { ra_deg: number; dec_deg: number }[], mx: number, my: number,
  w: number, h: number, maxPx = 12): number {
  let best = -1, bd = maxPx * maxPx;
  for (let i = 0; i < pts.length; i++) {
    const { px, py } = toPixel(pts[i].ra_deg, pts[i].dec_deg, w, h);
    const d = (px - mx) ** 2 + (py - my) ** 2;
    if (d <= bd) { bd = d; best = i; }
  }
  return best;
}
