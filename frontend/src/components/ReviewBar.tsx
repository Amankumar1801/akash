import { useEffect, useState } from "react";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { LabelRow, ReviewLabel } from "../api/types";

const OPTIONS: { v: ReviewLabel; text: string }[] = [
  { v: "interesting", text: "Interesting" }, { v: "needs_followup", text: "Needs follow-up" },
  { v: "uncertain", text: "Uncertain" }, { v: "not_interesting", text: "Not interesting" },
  { v: "false_positive", text: "False positive" },
];

export function ReviewBar({ id }: { id: string }) {
  const { api } = useApi();
  const [mine, setMine] = useState<LabelRow | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api.listLabels(id).then((r) => live && setMine(r.length ? r[r.length - 1] : null)).catch(() => undefined);
    return () => { live = false; };
  }, [api, id]);

  async function pick(v: ReviewLabel) {
    setBusy(true); setErr(null);
    try { setMine(await api.addLabel(id, v)); } catch (e) { setErr(explain(e)); } finally { setBusy(false); }
  }

  return (
    <div className="review" role="group" aria-label="Your review of this candidate">
      <span className="muted">Your review</span>
      {OPTIONS.map((o) => (
        <button key={o.v} type="button" disabled={busy} aria-pressed={mine?.label === o.v} onClick={() => void pick(o.v)}>{o.text}</button>))}
      {err && <span className="notice bad" role="alert">{err}</span>}
    </div>
  );
}
