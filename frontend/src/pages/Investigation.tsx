import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { EvidenceRow, InvestigationDetail, JobEvent, ObjectOut, ProvGraph, VariabilityResult } from "../api/types";
import { Ask } from "../components/Ask";
import { EvidenceStrip } from "../components/EvidenceStrip";
import { FoldPlot, LightCurvePlot, useEpoch } from "../components/LightCurvePlots";
import { ReportPanel } from "../components/ReportPanel";
import { ProvGraphView } from "../components/ProvGraph";
import { ReviewBar } from "../components/ReviewBar";
import { Recorder } from "../components/Recorder";
import { Sheet } from "../components/Sheet";
import { VariabilityPanel } from "../components/VariabilityPanel";
import { Verdict } from "../components/Verdict";
import { follow } from "../lib/follow";
import { cleanSeries, type Series } from "../lib/lc";
import { reduceLanes } from "../lib/phases";

type Tab = "summary" | "evidence" | "provenance" | "ask" | "report";
const EMPTY: Series = { t: [], f: [] };

export function Investigation() {
  const { id = "" } = useParams();
  const { api } = useApi();
  const [detail, setDetail] = useState<InvestigationDetail | null>(null);
  const [obj, setObj] = useState<ObjectOut | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRow[]>([]);
  const [prov, setProv] = useState<ProvGraph | null>(null);
  const [series, setSeries] = useState<Series>(EMPTY);
  const [vari, setVari] = useState<VariabilityResult | null>(null);
  const [err, setErr] = useState("");
  const [lost, setLost] = useState(false);
  const [tab, setTab] = useState<Tab>("summary");
  const [selected, setSelected] = useState<string | null>(null);
  const lcRequested = useRef(false);

  // reset when the investigation or data source changes
  useEffect(() => {
    setDetail(null); setObj(null); setEvents([]); setEvidence([]); setProv(null); setSeries(EMPTY);
    setErr(""); setLost(false); setTab("summary"); setSelected(null); lcRequested.current = false;
  }, [id, api]);

  const refresh = useCallback(async () => {
    const d = await api.getInvestigation(id);
    setDetail(d);
    return d;
  }, [api, id]);

  // follow the event stream to the end, then re-read the final state
  useEffect(() => {
    const ctl = new AbortController();
    (async () => {
      try {
        const d = await refresh();
        if (d.object_id) setObj(await api.getObject(d.object_id).catch(() => null));
        const res = await follow(api, id, (e) => setEvents((prev) => (prev.some((p) => p.seq === e.seq) ? prev : [...prev, e])), ctl.signal);
        if (res === "lost") setLost(true);
        if (res !== "aborted") await refresh();
      } catch (e) { if (!ctl.signal.aborted) setErr(explain(e)); }
    })();
    return () => ctl.abort();
  }, [api, id, refresh]);

  const lanes = useMemo(() => reduceLanes(events), [events]);
  const fetched = lanes[0].state === "done" || detail?.status === "succeeded";

  // load the light curve once the data has been fetched
  useEffect(() => {
    if (!fetched || !detail?.object_id || lcRequested.current) return;
    lcRequested.current = true;
    (async () => {
      try {
        const obs = await api.observations(detail.object_id as string);
        if (!obs.length) return;
        const lc = await api.observationData(obs[0].obs_id, 4000);
        setSeries(cleanSeries(lc.time_bjd, lc.flux, lc.quality_flagged));
        api.variability(obs[0].obs_id).then(setVari).catch(() => setVari(null));
      } catch { /* the plot is optional; the findings do not depend on it */ }
    })();
  }, [api, fetched, detail?.object_id]);

  // evidence and provenance once the run has finished
  useEffect(() => {
    if (detail?.status !== "succeeded") return;
    api.evidence(id).then(setEvidence).catch((e) => setErr(explain(e)));
    api.provenance(id).then(setProv).catch(() => setProv(null));
  }, [api, id, detail?.status]);

  const a = detail?.assessment ?? null;
  const period = a?.transit?.period_d.value ?? null;
  const t0 = useEpoch(series, period);
  const running = detail?.status === "queued" || detail?.status === "running";
  const openEvidence = (eid: string) => { setSelected(eid); setTab("evidence"); window.scrollTo({ top: 0, behavior: "smooth" }); };

  const cancel = async () => { try { setDetail({ ...(await api.cancelInvestigation(id)), object_id: detail?.object_id ?? null, assessment: null, n_evidence: null }); } catch (e) { setErr(explain(e)); } };

  if (err && !detail) return (
    <section className="section"><p className="notice bad" role="alert">{err}</p><p style={{ marginTop: 14 }}><Link to="/">Back to the logbook</Link></p></section>);

  return (
    <div className="inv">
      <aside className="rail" aria-label="Progress">
        <h2>{running ? "Working through the pipeline" : "How this was run"}</h2>
        <Recorder lanes={lanes} />
        {running && <p style={{ marginTop: 16 }}><button className="btn" onClick={() => void cancel()}>Cancel investigation</button></p>}
        {lost && <p className="notice bad" style={{ marginTop: 14 }}>The live connection dropped. Reload to see the latest state.</p>}
        <p className="muted" style={{ marginTop: 16, fontSize: 13.5 }}>
          Investigation {id.slice(0, 8)}. Every step is recorded with the code version and data hash it used.
        </p>
      </aside>

      <div className="main">
        <header className="obj">
          <h1>{obj?.canonical_name ?? (detail ? "Object" : "Loading")}</h1>
          <div className="meta num">
            {obj && <span>RA {obj.ra_deg.toFixed(4)}, Dec {obj.dec_deg.toFixed(4)}</span>}
            {obj?.aliases.slice(0, 2).map((x) => <span key={x.namespace}>{x.namespace} {x.identifier}</span>)}
          </div>
        </header>

        {detail?.status === "failed" && <p className="notice bad" role="alert" style={{ marginTop: 22 }}>This investigation failed: {detail.error ?? "unknown error"}. Nothing was recorded as a result.</p>}
        {detail?.status === "cancelled" && <p className="notice" style={{ marginTop: 22 }}>Cancelled before finishing. Nothing was recorded as a result.</p>}
        {running && <p className="notice" style={{ marginTop: 22 }}>Findings appear when every phase has finished. The light curve shows as soon as the data arrives.</p>}
        {err && detail && <p className="notice bad" role="alert" style={{ marginTop: 22 }}>{err}</p>}

        {detail?.status === "succeeded" && !a && (
          <section className="verdict" style={{ marginTop: 22 }}>
            <h2>No repeating dip stands above the noise</h2>
            <p className="prose">The search found nothing it could defend, so the classifier, anomaly and catalog steps were skipped. That says this data holds no detectable periodic signal, not that the star has no planets.</p>
          </section>
        )}
        {detail?.status === "succeeded" && <ReviewBar id={id} />}
        {a && <div style={{ marginTop: 18 }}><Verdict a={a} evidence={evidence} onOpenEvidence={openEvidence} /></div>}

        {series.t.length > 0 && (
          <div className="plots">
            <LightCurvePlot series={series} period={period} t0={t0} durationH={a?.transit?.duration_h ?? 0} />
            {period && a?.transit && <FoldPlot series={series} period={period} t0={t0} durationH={a.transit.duration_h} />}
          </div>
        )}
        {vari && vari.character !== "insufficient_data" && <VariabilityPanel v={vari} />}
        {period && series.t.length > 0 && (
          <p className="muted" style={{ fontSize: 13, marginTop: 8, maxWidth: "70ch" }}>
            The pipeline reports period, depth and duration. The centring of the folded curve is estimated in your browser for display only.
          </p>
        )}

        {detail?.status === "succeeded" && (
          <>
            <div className="tabs" role="tablist" aria-label="Result sections">
              {(["summary", "evidence", "provenance", "ask", "report"] as Tab[]).map((t) => (
                <button key={t} role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls={`panel-${t}`} onClick={() => setTab(t)}>
                  {{ summary: "Readouts", evidence: `Evidence${evidence.length ? ` (${evidence.length})` : ""}`, provenance: "Provenance", ask: "Ask", report: "Report" }[t]}
                </button>))}
            </div>
            <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
              {tab === "summary" && a && <Sheet a={a} />}
              {tab === "summary" && !a && <p className="empty">There are no readouts because no signal was found. The evidence tab shows what was checked.</p>}
              {tab === "evidence" && (evidence.length ? <EvidenceStrip rows={evidence} selected={selected} onSelect={setSelected} />
                : <div className="skel" style={{ height: 160, marginTop: 20 }} />)}
              {tab === "report" && <ReportPanel id={id} />}
              {tab === "ask" && <Ask id={id} onOpenEvidence={openEvidence} />}
              {tab === "provenance" && (prov ? <ProvGraphView g={prov} /> : <div className="skel" style={{ height: 160, marginTop: 20 }} />)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
