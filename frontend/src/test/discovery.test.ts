import { describe, expect, it } from "vitest";
import { DemoApi } from "../api/demo";
import { csvCell, toCsv } from "../lib/csv";
import { NOT_A_SCORE, signalStrength } from "../lib/feed";
import { nearest, project, toPixel, X_MAX, Y_MAX } from "../lib/sky";

describe("sky projection", () => {
  it("maps the centre to the origin and stays inside the ellipse", () => {
    const c = project(180, 0);
    expect(Math.abs(c.x)).toBeLessThan(1e-9); expect(Math.abs(c.y)).toBeLessThan(1e-9);
    for (const [ra, dec] of [[0.001, 0], [359.9, 0], [90, 60], [270, -60], [10, 89], [200, -89]]) {
      const { x, y } = project(ra, dec);
      expect((x / X_MAX) ** 2 + (y / Y_MAX) ** 2).toBeLessThanOrEqual(1.0001);
    }
  });
  it("puts increasing RA to the left", () => {
    expect(project(200, 0).x).toBeLessThan(project(160, 0).x);
  });
  it("finds the nearest point only within the radius", () => {
    const pts = [{ ra_deg: 180, dec_deg: 0 }, { ra_deg: 90, dec_deg: 30 }];
    const { px, py } = toPixel(90, 30, 800, 400);
    expect(nearest(pts, px + 3, py, 800, 400)).toBe(1);
    expect(nearest(pts, px + 80, py + 80, 800, 400)).toBe(-1);
  });
});

describe("csv", () => {
  it("neutralises spreadsheet formulas", () => {
    for (const v of ["=1+1", "+A1", "-2", "@SUM(A1)"]) expect(csvCell(v).startsWith("'")).toBe(true);
  });
  it("quotes separators and joins with CRLF", () => {
    expect(csvCell('a,"b"')).toBe('"a,""b"""');
    expect(toCsv([{ a: 1, b: "x" }], ["a", "b"])).toBe("a,b\r\n1,x\r\n");
  });
});

describe("feed rules", () => {
  it("bands signal strength", () => {
    expect(signalStrength(3)).toBe("weak"); expect(signalStrength(10)).toBe("moderate");
    expect(signalStrength(20)).toBe("strong"); expect(signalStrength(null)).toBe("none");
  });
  it("demo feed is ordered by triage, has no score, and carries the caveat", async () => {
    const api = new DemoApi();
    const page = await api.discoveries({ sort: "triage", reviewed: "any", limit: 50 });
    expect(page.ranking.caveat).toBe(NOT_A_SCORE);
    expect(JSON.stringify(page.items)).not.toMatch(/"score"/);
    const order = ["new_signal_review", "models_disagree", "insufficient_data", "known_candidate",
      "likely_systematic", "known_false_positive", "known_confirmed"];
    const idx = page.items.map((c) => order.indexOf(c.triage_category));
    expect([...idx].sort((a, b) => a - b)).toEqual(idx);
    const sky = await api.sky();
    expect(sky.points.length).toBeLessThanOrEqual(5000);
  });
});
