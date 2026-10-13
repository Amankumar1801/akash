import { useState } from "react";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { AskAnswer, StatementKind } from "../api/types";

const KIND: Record<StatementKind, string> = {
  fact: "Measured", prediction: "Model output", interpretation: "Reading",
  uncertainty: "Uncertainty", recommendation: "Suggestion",
};
const EXAMPLES = ["What does the evidence say?", "Why was it triaged this way?", "What is uncertain here?"];

export function Ask({ id, onOpenEvidence }: { id: string; onOpenEvidence: (eid: string) => void }) {
  const { api } = useApi();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskAnswer | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function go(text: string) {
    if (!text.trim() || busy) return;
    setBusy(true); setErr(null);
    try { setRes(await api.ask(id, text.trim())); }
    catch (e) { setErr(explain(e)); setRes(null); }
    finally { setBusy(false); }
  }

  return (
    <div className="ask">
      <form onSubmit={(e) => { e.preventDefault(); void go(q); }}>
        <label htmlFor="ask-q" className="muted">Ask about this investigation</label>
        <div className="ask-row">
          <input id="ask-q" value={q} maxLength={500} onChange={(e) => setQ(e.target.value)}
                 placeholder="For example: what is uncertain here?" autoComplete="off" />
          <button className="btn" disabled={busy || !q.trim()}>{busy ? "Checking" : "Ask"}</button>
        </div>
        <div className="ask-ex">
          {EXAMPLES.map((x) => <button type="button" key={x} onClick={() => { setQ(x); void go(x); }}>{x}</button>)}
        </div>
      </form>
      {err && <p className="notice bad" role="alert">{err}</p>}
      {res && (
        <section aria-live="polite" className="ask-ans">
          <p className="muted ask-mode">
            {res.mode === "llm" ? "Written by a model, then checked against the evidence."
              : "Assembled directly from the evidence. No model wrote this."}
            {res.note ? ` ${res.note}` : ""}
          </p>
          <ul>
            {res.statements.map((s, i) => (
              <li key={i}>
                <span className={`kind kind-${s.kind}`}>{KIND[s.kind]}</span>
                <span>{s.text}.</span>
                {s.evidence_ids.map((eid) => (
                  <button type="button" key={eid} className="cite num" onClick={() => onOpenEvidence(eid)}
                          aria-label={`Open evidence ${eid.slice(0, 8)}`}>{eid.slice(0, 6)}</button>))}
              </li>))}
          </ul>
          <p className="muted ask-disc">{res.disclaimer}</p>
        </section>
      )}
    </div>
  );
}
