import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { explain } from "../api/client";
import { SCENARIOS } from "../api/demo";
import { useApi } from "../api/settings";
import type { InvestigationDetail, ObjectOut } from "../api/types";
import { DirGlyph } from "../components/Glyphs";
import { CaseArt } from "../components/Scene";
import { Loader, Spinner } from "../components/Loader";
import { useActivity } from "../lib/activity";
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
  useActivity(busy);   // the logo sweeps only while a submitted investigation is really being created

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

  const [depth, setDepth] = useState("2");   // how many TESS sectors to download and search
  const go = async (query: string) => {
    if (!query.trim() || busy) return;
    setBusy(true); setErr("");
    try {
      const job = await api.createInvestigation({ query: query.trim(), mission: "tess", mode: "deep", max_observations: Number(depth) });
      nav(`/investigations/${job.investigation_id}`);
    } catch (e) { setErr(explain(e)); setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void go(q); };

  return (
    <>
      <section className="hero" aria-labelledby="hero-h">
        <Sky />
        <div className="hero-orb" aria-hidden="true">
          <svg viewBox="0 0 400 400" className="orb-rings" focusable="false">
            <ellipse cx="200" cy="200" rx="188" ry="52" className="orb-orbit" transform="rotate(-18 200 200)" />
            <g className="orb-scan"><circle cx="200" cy="200" r="176" className="orb-scan-ring" /></g>
            <circle cx="200" cy="200" r="150" className="orb-fine" />
            <circle cx="200" cy="200" r="196" className="orb-fine" strokeDasharray="1 7" />
          </svg>
          {/* A looping solar eclipse: the moon crosses the sun, totality, then it passes and repeats. Pure decoration. */}
          <i className="orb-sun" /><i className="orb-corona" /><i className="orb-moon" onAnimationIteration={(e) => e.currentTarget.style.setProperty("--moon-dy", `${(Math.random() * 10 - 5).toFixed(1)}%`)} />
        </div>
        <div className="hero-horizon" aria-hidden="true" />
        <div className="hero-inner">
          <span className="eyebrow">Explore</span>
          <h1 id="hero-h">Name a star. See what its light <em>can and can&apos;t tell you.</em></h1>
          <p className="prose">
            Akash searches a light curve for repeating dips, checks them against the catalogs, and keeps every
            finding as its own line of evidence. Nothing is averaged into a score.
          </p>
          <form className="search" onSubmit={submit}>
            <div className={`search-box${busy ? " busy" : ""}`}>
              <label htmlFor="q" className="visually-hidden">Star name or catalog ID</label>
              <input id="q" className="field" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" spellCheck={false}
                placeholder={settings.mode === "demo" ? "TIC 900000001" : "TIC 261136679, KIC 8462852, or a name"} />
              <button className="btn primary" type="submit" disabled={busy || !q.trim()}>{busy ? <><Spinner />Starting</> : "Investigate"}</button>
            </div>
            <div className="depth-row">
              <label htmlFor="depth" className="label-mono">Data to use</label>
              <select id="depth" className="field" value={depth} onChange={(e) => setDepth(e.target.value)} disabled={busy}>
                <option value="2">Quick look: 2 sectors</option>
                <option value="4">Standard: 4 sectors</option>
                <option value="10">Everything: up to 10 sectors (can take 30 minutes)</option>
              </select>
            </div>
            {err && <p className="err" role="alert" style={{ marginTop: 8 }}>{err}</p>}
          </form>
          <aside className="stats-panel" aria-label="Your logbook at a glance">
            <span className="label-mono">Your logbook</span>
            <dl>
              <div><dt>Investigations</dt><dd className="num">{log ? log.length : "\u2014"}</dd></div>
              <div><dt>Finished</dt><dd className="num">{log ? log.filter((e) => e.d.status === "succeeded").length : "\u2014"}</dd></div>
              <div><dt>Signals to review</dt><dd className="num">{log ? log.filter((e) => e.d.assessment?.triage_category === "new_signal_review").length : "\u2014"}</dd></div>
              <div><dt>No periodic signal</dt><dd className="num">{log ? log.filter((e) => e.d.outcome === "no_transit_signal").length : "\u2014"}</dd></div>
            </dl>
            <p className="muted">Counts the latest 12 of your investigations.</p>
          </aside>
          {settings.mode === "demo" && (
            <div>
              <p className="muted label-mono">Or start from one of eight synthetic cases</p>
              <ul className="demo-list">
                {SCENARIOS.map((s) => (
                  <li key={s.id}>
                    <button onClick={() => void go(`TIC ${900000000 + s.id}`)} disabled={busy}>
                      <CaseArt seed={s.id} />
                      <span className="id">TIC {900000000 + s.id}</span>
                      <span className="t">{s.title}</span><span className="s">{s.summary}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      <section className="section" aria-labelledby="log-h">
        <span className="eyebrow">Logbook</span>
        <h2 id="log-h">Recent investigations</h2>
        <p className="muted">Your recent investigations, newest first.</p>
        {logErr && <p className="notice bad" style={{ marginTop: 14 }}>{logErr}</p>}
        {!log && !logErr && <Loader label="Reading the logbook" />}
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
