export const pct = (x: number, d = 0): string => `${(x * 100).toFixed(d)}%`;
export const ppm = (x: number): string => `${Math.round(x).toLocaleString("en-US")} ppm`;
export function days(x: number): string {
  return x >= 10 ? `${x.toFixed(2)} d` : `${x.toFixed(3)} d`;
}
export function ago(tsSeconds: number, now = Date.now()): string {
  const s = Math.max(0, Math.round(now / 1000 - tsSeconds));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
export const short = (id: string, n = 8): string => id.slice(0, n);
export function renderValue(v: unknown): string {
  if (v === null || v === undefined) return "none";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toPrecision(4);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.map(renderValue).join(", ");
  return Object.entries(v as Record<string, unknown>)
    .map(([k, x]) => `${k.replace(/_/g, " ")} ${renderValue(x)}`).join("; ");
}
