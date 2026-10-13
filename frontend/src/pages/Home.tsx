import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { explain } from "../api/client";
import { SCENARIOS } from "../api/demo";
import { useApi } from "../api/settings";
import type { InvestigationDetail, ObjectOut } from "../api/types";
import { DirGlyph } from "../components/Glyphs";
import { Sky } from "../components/Sky";
import { ago } from "../lib/format";
import { TRIAGE } from "../lib/labels";

interface Entry { d: InvestigationDetail; o: ObjectOut | null }

export function Home() {
  const { api, settings } = useApi();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [log, setLog] = useState<Entry[] | null>(null);
  const [logErr, setLogErr] = useState("");

  useEffect(() => {
    let live = true;
    setLog(null); setLogErr("");
    (async () => {
      try {
        const jobs = (await api.listInvestigations()).slice(0, 12);
        const entries = await Promise.all(jobs.map(async (j) => {
          const d = await api.getInvestigation(j.investigation_id);
          const o = d.object_id ? await api.getObject(d.object_id).catch(() => null) : null;
          return { d, o };
        }));
        if (live) setLog(entries);
      } catch (e) { if (live) setLogErr(explain(e)); }
    })();
    return () => { live = false; };
  }, [api]);

  const go = async (query: string) => {
    if (!query.trim() || busy) return;
    setBusy(true); setErr("");
    try {
      const job = await api.createInvestigation({ query: query.trim(), mission: "tess", mode: "deep" });
      nav(`/investigations/${job.investigation_id}`);
    } catch (e) { setErr(explain(e)); setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void go(q); };

  return (
    <>
      <section className="hero paper" aria-labelledby="hero-h">
        <Sky />
        <div className="hero-inner">
          <h1 id="hero-h">Name a star. See what its light can and can't tell you.</h1>
          <p className="prose">
            Akash searches a light curve for repeating dips, checks them against the catalogs, and keeps every
            finding as its own line of evidence. Nothing is averaged into a score.
          </p>
          <form className="search" onSubmit={submit}>
            <div>
              <label htmlFor="q" className="visually-hidden">Star name or catalog ID</label>
              <input id="q" className="field" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" spellCheck={false}
                placeholder={settings.mode === "demo" ? "TIC 900000001" : "TIC 261136679, KIC 8462852, or a name"} />
              {err && <p className="err" role="alert" style={{ marginTop: 8 }}>{err}</p>}
            </div>
            <button className="btn primary" type="submit" disabled={busy || !q.trim()}>{busy ? "Starting" : "Investigate"}</button>
          </form>
          {settings.mode === "demo" && (
            <div>
              <p className="muted" style={{ marginBottom: 4 }}>Or start from one of eight synthetic cases</p>
              <ul className="demo-list">
                {SCENARIOS.map((s) => (
                  <li key={s.id}>
                    <button onClick={() => void go(`TIC ${900000000 + s.id}`)} disabled={busy}>
                      <span className="id">TIC {900000000 + s.id}</span>
                      <span><span className="t">{s.title}</span><span className="s">{s.summary}</span></span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      <section className="section" aria-labelledby="log-h">
        <h2 id="log-h">Logbook</h2>
        <p className="muted">Your recent investigations, newest first.</p>
        {logErr && <p className="notice bad" style={{ marginTop: 14 }}>{logErr}</p>}
        {!log && !logErr && <div className="skel" style={{ height: 120, marginTop: 14 }} aria-label="Loading" />}
        {log && log.length === 0 && <p className="empty">Nothing here yet. Investigate a star above and it will be recorded with every step and source.</p>}
        {log && log.length > 0 && (
          <div className="log" role="list">
            {log.map(({ d, o }) => {
              const cat = d.assessment?.triage_category;
              const t = cat ? TRIAGE[cat] : null;
              return (
                <Link key={d.investigation_id} to={`/investigations/${d.investigation_id}`} role="listitem">
                  <span className="nm">{o?.canonical_name ?? "Object"}</span>
                  <span className="tag">
                    {t ? <><DirGlyph d={t.tone} />{t.title}</>
                      : d.outcome === "no_transit_signal" ? <><DirGlyph d="inconclusive" />No periodic signal found</>
                      : <span className="muted">{{ queued: "Queued", running: "Running", failed: "Failed", cancelled: "Cancelled", succeeded: "Finished" }[d.status]}</span>}
                  </span>
                  <span className="when muted">{ago(d.created_at)}</span>
                  <span className="st muted">{o ? `${o.ra_deg.toFixed(1)}, ${o.dec_deg.toFixed(1)}` : ""}</span>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </>
  );
}
