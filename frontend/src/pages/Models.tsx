import { useEffect, useState } from "react";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { ModelOut } from "../api/types";

export function Models() {
  const { api } = useApi();
  const [rows, setRows] = useState<ModelOut[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    setRows(null); setErr("");
    api.models().then((m) => live && setRows(m)).catch((e) => live && setErr(explain(e)));
    return () => { live = false; };
  }, [api]);
  return (
    <section className="section">
      <h2>Models</h2>
      <p className="prose" style={{ marginTop: 6 }}>
        Every prediction records the model version, the data it learned from and the feature version, so a result can be reproduced.
        Versions are immutable once saved.
      </p>
      {err && <p className="notice bad" style={{ marginTop: 16 }}>{err}</p>}
      {!rows && !err && <div className="skel" style={{ height: 100, marginTop: 16 }} />}
      {rows && rows.length === 0 && <p className="empty">No models are saved in the registry yet. Train one with scripts/train_transit.py and it will appear here.</p>}
      {rows && rows.length > 0 && (
        <div className="scroll-x"><table className="tbl">
          <thead><tr><th>Model</th><th>Version</th><th>Saved</th><th>Features</th><th>Training data hash</th><th>Rows</th></tr></thead>
          <tbody>{rows.map((m) => (
            <tr key={`${m.name}/${m.version}`} style={{ cursor: "default" }}>
              <td><b>{m.name}</b></td><td>{m.version}</td><td>{m.created_at ? new Date(m.created_at).toLocaleDateString() : "unknown"}</td>
              <td>{m.feature_version ?? "unknown"}</td><td className="hash">{m.data_hash ?? "unknown"}</td>
              <td className="num">{m.n ? Object.entries(m.n).map(([k, v]) => `${k} ${v.toLocaleString("en-US")}`).join(", ") : "unknown"}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </section>
  );
}
