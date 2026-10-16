import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { DemoApi } from "../api/demo";
import imageSample from "../api/image_sample.json";
import { MAX_FITS_BYTES, b64ToFloat32, bytesToB64, fitsPayload, float32ToB64, heat, luminance, stretch, toRgba } from "../lib/image";

describe("image helpers", () => {
  it("round-trips float32 pixels through base64", () => {
    const a = new Float32Array([0, 1.5, -2.25, 1e6, 3.14159]);
    expect(Array.from(b64ToFloat32(float32ToB64(a)))).toEqual(Array.from(a));
  });
  it("decodes the sample to width x height pixels", () => {
    expect(b64ToFloat32(imageSample.pixels_b64)).toHaveLength(imageSample.width * imageSample.height);
  });
  it("stretches stay in 0..1, start at 0, end at 1 and never decrease", () => {
    for (const m of ["linear", "sqrt", "log", "asinh"] as const) {
      expect(stretch(-5, 0, 10, m)).toBe(0);
      expect(stretch(50, 0, 10, m)).toBeCloseTo(1, 9);
      let prev = -1;
      for (let v = 0; v <= 10; v += 0.5) { const t = stretch(v, 0, 10, m); expect(t).toBeGreaterThanOrEqual(prev); expect(t).toBeLessThanOrEqual(1); prev = t; }
    }
    expect(stretch(5, 3, 3, "linear")).toBe(0);                      // a flat range cannot divide by zero
  });
  it("builds opaque rgba for both colour maps", () => {
    for (const c of ["grey", "heat"] as const) {
      const out = toRgba(new Float32Array([0, 5, 10]), 0, 10, "linear", c);
      expect(out).toHaveLength(12);
      expect([out[3], out[7], out[11]]).toEqual([255, 255, 255]);
    }
    expect(heat(0)).toEqual([0, 0, 0]);
  });
  it("converts rgba to luminance", () => {
    const l = luminance(new Uint8Array([255, 255, 255, 255, 0, 0, 0, 255]));
    expect(l[0]).toBeCloseTo(255, 3); expect(l[1]).toBe(0);
  });
  it("checks FITS files before sending them", () => {
    const ok = new TextEncoder().encode("SIMPLE  =                    T" + " ".repeat(100));
    expect(fitsPayload(ok.buffer as ArrayBuffer)).toEqual({ fits_b64: bytesToB64(ok) });
    expect(fitsPayload(new TextEncoder().encode("<html>nope</html>").buffer as ArrayBuffer)).toMatch(/does not look like a FITS/);
    expect(fitsPayload(new ArrayBuffer(MAX_FITS_BYTES + 1))).toMatch(/limit/);
  });
});

describe("demo api image analysis", () => {
  it("returns the precomputed measurements for its own sample, with no class label", async () => {
    const r = await new DemoApi().analyzeImage({ pixels_b64: imageSample.pixels_b64, width: imageSample.width, height: imageSample.height });
    expect(r.precomputed).toBe(true);
    expect(r.status).toBe("source_measured");
    expect(r.source!.concentration).toBeGreaterThan(2);
    expect(JSON.stringify(r).toLowerCase()).not.toMatch(/"(spiral|elliptical|merger)"/);
  });
  it("refuses anything else rather than inventing numbers", async () => {
    await expect(new DemoApi().analyzeImage({ pixels_b64: "AAAA", width: 16, height: 16 })).rejects.toBeInstanceOf(ApiError);
  });
});
