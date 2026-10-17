import { useEffect, useMemo, useRef, useState } from "react";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import imageSample from "../api/image_sample.json";
import type { ImageRequest, ImageResult } from "../api/types";
import { b64ToFloat32, fitsPayload, float32ToB64, luminance, toRgba, type Stretch } from "../lib/image";
import { PageHead } from "../components/PageHead";

const MAX_DECODED_SIDE = 256;
const FACTS: [keyof NonNullable<ImageResult["source"]>, string, string, (v: number) => string][] = [
  ["concentration", "Concentration", "How tightly the light is packed toward the centre. Higher means more concentrated.", (v) => v.toFixed(2)],
  ["asymmetry", "Asymmetry", "How much the image differs from itself turned half a circle, with noise removed. 0 is perfectly symmetric.", (v) => v.toFixed(2)],
  ["ellipticity", "Ellipticity", "0 is round; values toward 1 are more elongated.", (v) => v.toFixed(2)],
  ["position_angle_deg", "Position angle", "Direction of the long axis, in degrees from the image x axis.", (v) => `${v.toFixed(0)} deg`],
  ["r50_px", "Half-light radius", "Radius holding half of the light, in pixels.", (v) => `${v.toFixed(1)} px`],
  ["r20_px", "r20", "Radius holding a fifth of the light, in pixels.", (v) => `${v.toFixed(1)} px`],
  ["r80_px", "r80", "Radius holding four fifths of the light, in pixels.", (v) => `${v.toFixed(1)} px`],
  ["snr", "Detection significance", "Total signal over the noise it would have by chance.", (v) => v.toFixed(0)],
];

async function decodePicture(file: File): Promise<ImageRequest | string> {
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, MAX_DECODED_SIDE / Math.max(bmp.width, bmp.height));
  const w = Math.max(1, Math.round(bmp.width * k)), h = Math.max(1, Math.round(bmp.height * k));
  if (Math.min(w, h) < 16) return "That picture is too small. Each side must be at least 16 pixels.";
  const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
  const ctx = cv.getContext("2d");
  if (!ctx) return "This browser cannot read pictures.";
  ctx.drawImage(bmp, 0, 0, w, h);
  return { pixels_b64: float32ToB64(luminance(ctx.getImageData(0, 0, w, h).data)), width: w, height: h };
}

export function ImageViewer() {
  const { api } = useApi();
  const [req, setReq] = useState<ImageRequest | null>(null);
  const [label, setLabel] = useState("");
  const [res, setRes] = useState<ImageResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Stretch>("asinh");
  const [cmap, setCmap] = useState<"grey" | "heat">("grey");
  const [zoom, setZoom] = useState(3);
  const [overlay, setOverlay] = useState(true);
  const cv = useRef<HTMLCanvasElement>(null);

  const useSample = () => {
    setReq({ pixels_b64: imageSample.pixels_b64, width: imageSample.width, height: imageSample.height });
    setLabel("synthetic sample"); setRes(null); setErr(null);
  };
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setRes(null); setErr(null); setLabel(f.name.slice(0, 80));
    try {
      if (/\.(fits?|fts)$/i.test(f.name)) {
        const p = fitsPayload(await f.arrayBuffer());
        if (typeof p === "string") { setErr(p); setReq(null); } else setReq(p);
      } else if (/^image\/(png|jpeg)$/.test(f.type)) {
        const p = await decodePicture(f);
        if (typeof p === "string") { setErr(p); setReq(null); } else setReq(p);
      } else { setErr("Use a FITS file (.fits) or a PNG or JPEG picture."); setReq(null); }
    } catch { setErr("That file could not be read."); setReq(null); }
  };
  const analyse = async () => {
    if (!req) return;
    setBusy(true); setErr(null);
    try { setRes(await api.analyzeImage({ ...req, label: label || undefined })); }
    catch (e) { setErr(explain(e)); setRes(null); } finally { setBusy(false); }
  };

  const px = useMemo(() => (res ? b64ToFloat32(res.preview.pixels_b64) : null), [res]);
  useEffect(() => {
    if (!res || !px || !cv.current) return;
    const { width, height, vmin, vmax } = res.preview;
    const c = cv.current; c.width = width; c.height = height;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.putImageData(new ImageData(toRgba(px, vmin, vmax, mode, cmap) as unknown as Uint8ClampedArray<ArrayBuffer>, width, height), 0, 0);
  }, [res, px, mode, cmap]);

  const k = res?.preview.factor ?? 1;
  const s = res?.source ?? null;
  const flip = res?.input_kind === "fits";
  return (
    <section className="section">
      <PageHead eyebrow="Images" title="Look at the" accent="evidence directly.">
        Open a single-band image of a galaxy or other extended object (a FITS cutout, or a PNG or JPEG). AKASH measures how the light
        is distributed. It does not say what kind of object it is.
      </PageHead>
      <div className="spec-actions" style={{ marginTop: 14 }}>
        <label className="btn">Open an image
          <input type="file" accept=".fits,.fit,.fts,image/png,image/jpeg" hidden onChange={(e) => void onFile(e.target.files?.[0])} /></label>
        <button className="btn" onClick={useSample}>Use the synthetic sample</button>
        <button className="btn primary" onClick={() => void analyse()} disabled={!req || busy}>{busy ? "Analysing" : "Analyse"}</button>
        {req && <span className="muted">{label || "image ready"}</span>}
      </div>
      {err && <p className="notice bad" role="alert" style={{ marginTop: 12 }}>{err}</p>}

      {res && px && (
        <div style={{ marginTop: 18 }}>
          {res.precomputed && <p className="muted" style={{ fontSize: 13.5 }}>Demo mode: this analysis was computed ahead of time by the Python code on the synthetic sample.</p>}
          <div className="img-controls">
            <label>Stretch <select value={mode} onChange={(e) => setMode(e.target.value as Stretch)}>
              <option value="linear">Linear</option><option value="sqrt">Square root</option><option value="log">Logarithmic</option><option value="asinh">Asinh</option></select></label>
            <label>Colour <select value={cmap} onChange={(e) => setCmap(e.target.value as "grey" | "heat")}>
              <option value="grey">Grey</option><option value="heat">Heat</option></select></label>
            <label>Zoom <input type="range" min={1} max={5} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} aria-valuetext={`${zoom} times`} /></label>
            <label className="check"><input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} /> Show centre and radii</label>
          </div>
          <div className="img-stage">
            <div className="img-frame" style={{ width: res.preview.width * zoom, height: res.preview.height * zoom,
              transform: flip ? "scaleY(-1)" : undefined }}>
              <canvas ref={cv} role="img" aria-label={`Image, ${res.width} by ${res.height} pixels. Measurements follow in a table.`}
                      style={{ width: "100%", height: "100%", imageRendering: "pixelated" }} />
              {overlay && s && (
                <svg viewBox={`0 0 ${res.preview.width} ${res.preview.height}`} className="img-overlay" aria-hidden="true">
                  {[s.r20_px, s.r50_px, s.r80_px].map((r, i) => (
                    <circle key={i} cx={s.centroid_xy[0] / k + 0.5} cy={s.centroid_xy[1] / k + 0.5} r={r / k} fill="none"
                            stroke="var(--lamp)" strokeWidth={0.6} strokeDasharray={i === 1 ? undefined : "2 2"} />))}
                  <path d={`M${s.centroid_xy[0] / k - 2} ${s.centroid_xy[1] / k + 0.5}h4M${s.centroid_xy[0] / k + 0.5} ${s.centroid_xy[1] / k - 2}v4`}
                        stroke="var(--supports)" strokeWidth={0.6} />
                </svg>)}
            </div>
          </div>
          {res.preview.factor > 1 && <p className="muted" style={{ fontSize: 13 }}>Shown at 1/{res.preview.factor} size. Measurements use the full image.</p>}

          {res.status === "no_source_detected" || !s ? (
            <p className="notice" style={{ marginTop: 14 }}>No source stood out from the noise, so nothing was measured.</p>
          ) : (
            <div className="scroll-x" style={{ marginTop: 14 }}><table className="tbl">
              <thead><tr><th>Measure</th><th>Value</th><th>What it means</th></tr></thead>
              <tbody>{FACTS.map(([key, name, what, fmt]) => (
                <tr key={key} style={{ cursor: "default" }}><td><b>{name}</b></td><td className="num">{fmt(s[key] as number)}</td><td className="muted">{what}</td></tr>))}</tbody>
            </table></div>)}
          <ul className="muted" style={{ fontSize: 13.5, marginTop: 14, paddingLeft: 18 }}>{res.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
          <p className="muted" style={{ fontSize: 13 }}>Input hash {res.input_sha256.slice(0, 16)}. Background {res.background.toFixed(2)}, noise {res.noise_rms.toFixed(2)}.</p>
        </div>
      )}
    </section>
  );
}
