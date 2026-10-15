import { useEffect, useState } from "react";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { ModelDetail, ModelOut } from "../api/types";

const key = (m: ModelOut) => `${m.name}/${m.version}`;
const show = (v: unknown): string => (v !== null && typeof v === "object" ? JSON.stringify(v, null, 2) : String(v));

export function Models() {
  const { api } = useApi();
  const [rows, setRows] = useState<ModelOut[] | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<ModelOut | null>(null);
  const [detail, setDetail] = useState<ModelDetail | null>(null);
  const [derr, setDerr] = useState("");

  useEffect(() => {
    let live = true;
    setRows(null); setErr("");
    api.models().then((m) => live && setRows(m)).catch((e) => live && setErr(explain(e)));
    return () => { live = false; };
  }, [api]);

  useEffect(() => {
    if (!open) { setDetail(null); return; }
    let live = true;
    setDetail(null); setDerr("");
    api.modelDetail(open.name, open.version).then((d) => live && setDetail(d)).catch((e) => live && setDerr(explain(e)));
    return () => { live = false; };
  }, [api, open]);

  return (
    <section className="section">
      <h2>Model observatory</h2>
      <p className="prose" style={{ marginTop: 6 }}>
        Every prediction records the model version, the data it learned from and the feature version, so a result can be reproduced.
        Versions are immutable once saved. Select a row to read its recorded metadata and model card.
      </p>
      {err && <p className="notice bad" style={{ marginTop: 16 }}>{err}</p>}
      {!rows && !err && <div className="skel" style={{ height: 100, marginTop: 16 }} />}
      {rows && rows.length === 0 && <p className="empty">No models are saved in the registry yet. Train one with scripts/train_transit.py and it will appear here.</p>}
      {rows && rows.length > 0 && (
        <div className="scroll-x"><table className="tbl">
          <thead><tr><th>Model</th><th>Version</th><th>Saved</th><th>Features</th><th>Training data hash</th><th>Rows</th></tr></thead>
          <tbody>{rows.map((m) => (
            <tr key={key(m)} tabIndex={0} aria-selected={open ? key(open) === key(m) : false}
                onClick={() => setOpen(open && key(open) === key(m) ? null : m)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(open && key(open) === key(m) ? null : m); } }}>
              <td><b>{m.name}</b></td><td>{m.version}</td><td>{m.created_at ? new Date(m.created_at).toLocaleDateString() : "unknown"}</td>
              <td>{m.feature_version ?? "unknown"}</td><td className="hash">{m.data_hash ?? "unknown"}</td>
              <td className="num">{m.n ? Object.entries(m.n).map(([k, v]) => `${k} ${v.toLocaleString("en-US")}`).join(", ") : "unknown"}</td>
            </tr>))}</tbody>
        </table></div>
      )}
      {open && (
        <article className="model-detail" aria-label={`${open.name} ${open.version}`}>
          <h3>{open.name} {open.version}</h3>
          {derr && <p className="notice bad" role="alert">{derr}</p>}
          {!detail && !derr && <div className="skel" style={{ height: 80 }} />}
          {detail && (<>
            <dl className="dgrid">{Object.entries(detail.metadata).map(([k, v]) => (
              <div key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{typeof v === "object" && v !== null ? <pre className="meta-pre">{show(v)}</pre> : show(v)}</dd></div>))}</dl>
            <h4>Model card</h4>
            {detail.model_card ? <pre className="meta-pre card-text">{detail.model_card}</pre> : <p className="empty">This version has no model card.</p>}
          </>)}
        </article>
      )}
    </section>
  );
}
