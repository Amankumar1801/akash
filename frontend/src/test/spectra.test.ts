import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { DemoApi } from "../api/demo";
import sample from "../api/spectrum_sample.json";
import { parseSpectrumCsv } from "../lib/spectrumCsv";

const rows = (n: number, extra = "") => Array.from({ length: n }, (_, i) => `${4000 + i * 2},${10 + (i % 3)}${extra}`).join("\n");

describe("spectrum csv parsing", () => {
  it("reads comma, tab and space separated rows and skips a header and comments", () => {
    const p = parseSpectrumCsv(`# comment\nwavelength,flux\n${rows(60)}`);
    expect(typeof p).not.toBe("string");
    if (typeof p !== "string") { expect(p.wavelength_a).toHaveLength(60); expect(p.flux_err).toBeNull(); }
    const t = parseSpectrumCsv(Array.from({ length: 60 }, (_, i) => `${4000 + i}\t10\t0.1`).join("\n"));
    if (typeof t !== "string") expect(t.flux_err?.[0]).toBe(0.1); else throw new Error(t);
  });
  it("turns unreadable flux into null rather than failing", () => {
    const p = parseSpectrumCsv(rows(60).replace("4010,12", "4010,nan"));
    if (typeof p === "string") throw new Error(p);
    expect(p.flux.filter((v) => v === null)).toHaveLength(1);
  });
  it("explains what is wrong", () => {
    expect(parseSpectrumCsv(rows(10))).toMatch(/at least 50/);
    expect(parseSpectrumCsv(`${rows(60)}\nfoo,bar`)).toMatch(/Could not read/);
    expect(parseSpectrumCsv(rows(20_001))).toMatch(/Too many rows/);
  });
  it("does not execute or interpret content", () => {
    expect(parseSpectrumCsv(`${rows(60)}\n=cmd|' /c calc'!A1,1`)).toMatch(/Could not read/);
  });
});

describe("demo api for phase 12", () => {
  it("returns the precomputed analysis only for its own sample", async () => {
    const api = new DemoApi();
    const r = await api.analyzeSpectrum({ wavelength_a: sample.wavelength_a, flux: sample.flux });
    expect(r.precomputed).toBe(true);
    expect(r.redshift.status).toBe("candidate_redshift");
    expect(Math.abs(r.redshift.candidates[0].z - sample.synthetic_truth_z)).toBeLessThan(1e-3);
    const other = sample.flux.slice(); other[3] = 99;
    await expect(api.analyzeSpectrum({ wavelength_a: sample.wavelength_a, flux: other })).rejects.toBeInstanceOf(ApiError);
  });
  it("says variability needs a live API and serves model detail", async () => {
    const api = new DemoApi();
    await expect(api.variability("x")).rejects.toMatchObject({ code: "demo_unavailable" });
    const m = (await api.models())[0];
    const d = await api.modelDetail(m.name, m.version);
    expect(d.model_card).toContain(m.name);
    await expect(api.modelDetail("nope", "v9")).rejects.toMatchObject({ status: 404 });
  });
});
