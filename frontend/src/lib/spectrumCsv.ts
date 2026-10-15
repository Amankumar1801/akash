export const MAX_ROWS = 20_000;
export const MIN_ROWS = 50;
export interface ParsedSpectrum { wavelength_a: number[]; flux: (number | null)[]; flux_err: (number | null)[] | null }

/** Parse "wavelength flux [error]" rows separated by commas, tabs or spaces. Returns a reason on failure. */
export function parseSpectrumCsv(text: string): ParsedSpectrum | string {
  const w: number[] = [], f: (number | null)[] = [], e: (number | null)[] = [];
  let hasErr = false;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const parts = line.split(/[\s,;]+/).filter(Boolean);
    const x = Number(parts[0]);
    if (parts.length < 2 || !Number.isFinite(x)) {
      if (w.length === 0) continue;                       // a header row before the data
      return `Could not read this row as numbers: "${line.slice(0, 40)}"`;
    }
    const y = Number(parts[1]);
    w.push(x); f.push(Number.isFinite(y) ? y : null);
    if (parts.length >= 3) { hasErr = true; const s = Number(parts[2]); e.push(Number.isFinite(s) ? s : null); } else e.push(null);
    if (w.length > MAX_ROWS) return `Too many rows. The limit is ${MAX_ROWS.toLocaleString("en-US")}.`;
  }
  if (w.length < MIN_ROWS) return `Need at least ${MIN_ROWS} rows of "wavelength flux", found ${w.length}.`;
  return { wavelength_a: w, flux: f, flux_err: hasErr ? e : null };
}
