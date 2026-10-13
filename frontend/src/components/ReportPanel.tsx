import { useState } from "react";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { ReportFile } from "../api/types";

function save(f: ReportFile) {
  const url = URL.createObjectURL(new Blob([f.text], { type: f.mime }));
  const a = document.createElement("a");
  a.href = url; a.download = f.filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ReportPanel({ id }: { id: string }) {
  const { api } = useApi();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [md, setMd] = useState<string | null>(null);

  async function get(format: "markdown" | "html", download: boolean) {
    setBusy(true); setErr(null);
    try {
      const f = await api.report(id, format);
      if (download) save(f); else setMd(f.text);
    } catch (e) { setErr(explain(e)); } finally { setBusy(false); }
  }

  return (
    <div className="ask">
      <p className="prose">
        A sectioned report assembled from the stored evidence. Measured facts, model outputs
        and written interpretations are kept apart, every statement cites its evidence, and nothing
        is written by a model.
      </p>
      <div className="ask-row" style={{ flexWrap: "wrap" }}>
        <button className="btn" disabled={busy} onClick={() => void get("markdown", false)}>Preview</button>
        <button className="btn" disabled={busy} onClick={() => void get("markdown", true)}>Download Markdown</button>
        <button className="btn" disabled={busy} onClick={() => void get("html", true)}>Download HTML</button>
      </div>
      {err && <p className="notice bad" role="alert">{err}</p>}
      {md && <pre className="report-pre" aria-label="Report preview">{md}</pre>}
    </div>
  );
}
