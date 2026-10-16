export type Stretch = "linear" | "sqrt" | "log" | "asinh";
export const MAX_FITS_BYTES = 675_000;

export function b64ToFloat32(b64: string): Float32Array {
  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return new Float32Array(buf.buffer, 0, Math.floor(buf.length / 4));
}

export function bytesToB64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export function float32ToB64(a: Float32Array): string {
  return bytesToB64(new Uint8Array(a.buffer, a.byteOffset, a.byteLength));
}

/** Map a value to 0..1 for display. Out-of-range values are clipped. */
export function stretch(v: number, lo: number, hi: number, mode: Stretch): number {
  const t = hi > lo ? Math.min(1, Math.max(0, (v - lo) / (hi - lo))) : 0;
  switch (mode) {
    case "sqrt": return Math.sqrt(t);
    case "log": return Math.log10(1 + 999 * t) / 3;
    case "asinh": return Math.asinh(10 * t) / Math.asinh(10);
    default: return t;
  }
}

export function heat(t: number): [number, number, number] {
  const r = Math.min(1, t * 2.2), g = Math.min(1, Math.max(0, t * 2.2 - 0.7)), b = Math.min(1, Math.max(0, t * 3 - 2));
  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

export function toRgba(px: Float32Array, lo: number, hi: number, mode: Stretch, cmap: "grey" | "heat"): Uint8ClampedArray {
  const out = new Uint8ClampedArray(px.length * 4);
  for (let i = 0; i < px.length; i++) {
    const t = stretch(px[i], lo, hi, mode);
    const [r, g, b] = cmap === "heat" ? heat(t) : [Math.round(t * 255), Math.round(t * 255), Math.round(t * 255)];
    out[4 * i] = r; out[4 * i + 1] = g; out[4 * i + 2] = b; out[4 * i + 3] = 255;
  }
  return out;
}

/** Whether a FITS file is small enough to send, or the reason it is not. */
export function fitsPayload(buf: ArrayBuffer): string | { fits_b64: string } {
  if (buf.byteLength > MAX_FITS_BYTES) return `That file is ${(buf.byteLength / 1000).toFixed(0)} kB. The limit is ${(MAX_FITS_BYTES / 1000).toFixed(0)} kB, so cut out a smaller region.`;
  const head = new TextDecoder().decode(new Uint8Array(buf, 0, Math.min(9, buf.byteLength)));
  if (head !== "SIMPLE  =") return "That does not look like a FITS file.";
  return { fits_b64: bytesToB64(new Uint8Array(buf)) };
}

/** Grey float pixels from RGBA, using the usual luminance weights. */
export function luminance(rgba: Uint8ClampedArray | Uint8Array): Float32Array {
  const out = new Float32Array(rgba.length / 4);
  for (let i = 0; i < out.length; i++) out[i] = 0.2126 * rgba[4 * i] + 0.7152 * rgba[4 * i + 1] + 0.0722 * rgba[4 * i + 2];
  return out;
}
