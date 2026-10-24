import { useCallback, useEffect, useRef, useState } from "react";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import type { DiscoveryCard, DiscoveryPage, FeedQuery, FeedSort, TriageCategory } from "../api/types";
import { DiscoveryCardView } from "../components/DiscoveryCardView";
import { toCsv } from "../lib/csv";
import { toFeedQuery, type Interpretation } from "../lib/nlquery";
import { TRIAGE } from "../lib/labels";
import { Loader } from "../components/Loader";
import { PageHead } from "../components/PageHead";
import { Scene } from "../components/Scene";

const SORTS: { v: FeedSort; t: string }[] = [
  { v: "triage", t: "Review order" }, { v: "anomaly", t: "Anomaly percentile" },
  { v: "snr", t: "Signal-to-noise" }, { v: "recent", t: "Most recent" },
];
const PAGE = 12;
const COLS = ["name", "triage_category", "anomaly_percentile", "snr", "period_d", "prediction", "known_status", "data_quality", "investigation_id"];

function save(text: string, name: string, mime: string) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function Discoveries() {
  const { api } = useApi();
  const [q, setQ] = useState<FeedQuery>({ sort: "triage", exclude_known: false, reviewed: "any" });
  const [page, setPage] = useState(0);
  const [data, setData] = useState<DiscoveryPage | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [ask, setAsk] = useState("");
  const [interp, setInterp] = useState<Interpretation | null>(null);
  const [intro, setIntro] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const seen = useRef(false);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!ask.trim()) return;
    try {
      const i = await api.interpretQuery(ask.trim());
      setInterp(i); setQ(toFeedQuery(i, { sort: "triage", reviewed: "any" })); setPage(0); setErr(null);
    } catch (x) { setErr(explain(x)); }
  }

  const load = useCallback(() => {
    let live = true;
    setErr(null);
    api.discoveries({ ...q, limit: PAGE, offset: page * PAGE })
      .then((d) => live && setData(d)).catch((e) => live && setErr(explain(e)));
    return () => { live = false; };
  }, [api, q, page]);
  useEffect(() => load(), [load]);
  // First arrival of results: records settle in with a stagger (once). Later changes (filters, review)
  // only get a brief fade of the list, never the entrance again.
  useEffect(() => {
    if (!data) return;
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!seen.current) {
      seen.current = true;
      if (!calm) { setIntro(true); const id = window.setTimeout(() => setIntro(false), 1400); return () => window.clearTimeout(id); }
    } else if (!calm) listRef.current?.animate([{ opacity: 0.5 }, { opacity: 1 }], { duration: 220, easing: "ease-out" });
  }, [data]);

  const set = (patch: Partial<FeedQuery>) => { setQ({ ...q, ...patch }); setPage(0); };
  const toggleCat = (c: TriageCategory) => {
    const cur = new Set(q.category ?? []); cur.has(c) ? cur.delete(c) : cur.add(c);
    set({ category: cur.size ? [...cur] : undefined });
  };

  async function markReviewed(c: DiscoveryCard) {
    setBusy(true);
    try { await api.addLabel(c.investigation_id, "uncertain"); load(); } catch (e) { setErr(explain(e)); } finally { setBusy(false); }
  }
  async function report(c: DiscoveryCard) {
    setBusy(true);
    try { const f = await api.report(c.investigation_id, "markdown"); save(f.text, f.filename, f.mime); }
    catch (e) { setErr(explain(e)); } finally { setBusy(false); }
  }
  function exportCsv() {
    if (!data) return;
    const rows = data.items.map((c) => ({
      name: c.name, triage_category: c.triage_category, anomaly_percentile: c.anomaly?.percentile ?? "",
      snr: c.transit?.snr ?? "", period_d: c.transit?.period_d ?? "", prediction: c.prediction?.probability ?? "",
      known_status: c.known_status ?? "", data_quality: c.data_quality, investigation_id: c.investigation_id }));
    save(toCsv(rows, COLS), "akash-candidates.csv", "text/csv");
  }

  const cmp = data?.items.filter((c) => picked.includes(c.investigation_id)) ?? [];
  return (
    <section className="section">
      <Scene name="candidates" />
      <PageHead eyebrow="Candidates" title="Signals worth" accent="a closer look.">
        Finished investigations, ordered for human review. The order is a fixed, stated rule. It is not a score and it is not a
        likelihood that anything is real.
      </PageHead>

      <form className="nl-search" onSubmit={(e) => void search(e)} role="search">
        <label>Describe what you want to see
          <input value={ask} maxLength={200} onChange={(e) => setAsk(e.target.value)}
                 placeholder="new strong signals not in a catalog, anomaly above 95, not reviewed" /></label>
        <button className="btn primary" type="submit">Search</button>
      </form>
      {interp && (
        <div className="nl-interp" aria-live="polite">
          <p className="muted">Read as:</p>
          <ul>{interp.understood.map((u, i) => <li key={i}><q>{u.phrase}</q> {"\u2192"} {u.effect}</li>)}</ul>
          {interp.understood.length === 0 && <p className="muted">Nothing in that request matched a filter, so the whole queue is shown.</p>}
          {interp.not_understood.length > 0 && <p className="notice">Not understood, so ignored: {interp.not_understood.join(", ")}.</p>}
          {interp.unsupported.map((u) => <p key={u.phrase} className="notice">{`"${u.phrase}": ${u.why}.`}</p>)}
          {interp.notes.map((n) => <p key={n} className="muted">{n}</p>)}
          <p className="muted">This reads fixed phrases; it does not use a language model. The filters below are what ran, and you can change them.</p>
        </div>)}

      <div className="feed-filters" role="group" aria-label="Filters">
        <label>Sort
          <select value={q.sort} onChange={(e) => set({ sort: e.target.value as FeedSort })}>
            {SORTS.map((s) => <option key={s.v} value={s.v}>{s.t}</option>)}</select></label>
        <label>Anomaly percentile at least
          <input type="number" min={0} max={100} value={q.min_anomaly_percentile ?? ""} placeholder="any"
                 onChange={(e) => set({ min_anomaly_percentile: e.target.value === "" ? undefined : Number(e.target.value) })} /></label>
        <label>Signal-to-noise at least
          <input type="number" min={0} value={q.min_snr ?? ""} placeholder="any"
                 onChange={(e) => set({ min_snr: e.target.value === "" ? undefined : Number(e.target.value) })} /></label>
        <label>Review
          <select value={q.reviewed} onChange={(e) => set({ reviewed: e.target.value as FeedQuery["reviewed"] })}>
            <option value="any">Any</option><option value="unreviewed">Not reviewed by me</option><option value="reviewed">Reviewed by me</option></select></label>
        <label>Name contains
          <input value={q.q ?? ""} maxLength={60} onChange={(e) => set({ q: e.target.value || undefined })} /></label>
        <label className="check"><input type="checkbox" checked={!!q.exclude_known} onChange={(e) => set({ exclude_known: e.target.checked })} /> Hide objects already in a catalog</label>
      </div>
      <div className="feed-cats" role="group" aria-label="Triage categories">
        {(Object.keys(TRIAGE) as TriageCategory[]).map((c) => (
          <button key={c} type="button" aria-pressed={q.category?.includes(c) ?? false} onClick={() => toggleCat(c)}>{TRIAGE[c].title}</button>))}
      </div>

      {err && <p className="notice bad" role="alert" style={{ marginTop: 14 }}>{err}</p>}
      {!data && !err && <Loader variant="inline" label="Reading the candidate queue" />}
      {data && (
        <>
          <p className="muted" style={{ marginTop: 14, fontSize: 13.5 }} aria-live="polite">
            {data.total} candidate{data.total === 1 ? "" : "s"}. {data.ranking.rule} {data.ranking.caveat}
            {data.truncated ? " Only the most recent investigations were scanned." : ""}{" "}
            <button className="linkish" onClick={exportCsv} disabled={!data.items.length}>Export this page as CSV</button>
          </p>
          {data.items.length === 0 && <p className="empty">Nothing matches. Investigations that found no signal are not candidates, and each object shows only its latest investigation.</p>}
          <div ref={listRef} className={`dlist${intro ? " reveal" : ""}`}>
            {data.items.map((c, i) => (
              <DiscoveryCardView key={c.investigation_id} c={c} busy={busy} index={i}
                picked={picked.includes(c.investigation_id)}
                onPick={() => setPicked((p) => p.includes(c.investigation_id) ? p.filter((x) => x !== c.investigation_id) : [...p.slice(-2), c.investigation_id])}
                onReviewed={() => void markReviewed(c)} onReport={() => void report(c)} />))}
          </div>
          <nav className="pager" aria-label="Pages">
            <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="muted">Page {page + 1} of {Math.max(1, Math.ceil(data.total / PAGE))}</span>
            <button className="btn" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>Next</button>
          </nav>
        </>
      )}
      {cmp.length >= 2 && (
        <div className="scroll-x" style={{ marginTop: 22 }}><table className="tbl">
          <caption className="muted" style={{ textAlign: "left", padding: "6px 0" }}>Side by side. Nothing is combined; read each row.</caption>
          <thead><tr><th></th>{cmp.map((c) => <th key={c.investigation_id}>{c.name}</th>)}</tr></thead>
          <tbody>
            {([["Category", (c: DiscoveryCard) => TRIAGE[c.triage_category].title],
              ["Anomaly percentile", (c: DiscoveryCard) => c.anomaly ? `${Math.round(c.anomaly.percentile)} (${c.anomaly.reference_population})` : "n/a"],
              ["Signal-to-noise", (c: DiscoveryCard) => c.transit ? c.transit.snr.toFixed(1) : "n/a"],
              ["Period (days)", (c: DiscoveryCard) => c.transit ? c.transit.period_d.toFixed(3) : "n/a"],
              ["Model probability", (c: DiscoveryCard) => c.prediction ? `${(c.prediction.probability * 100).toFixed(0)}%` : "n/a"],
              ["Catalog", (c: DiscoveryCard) => c.known_status ?? "not checked"],
              ["Data quality", (c: DiscoveryCard) => c.data_quality],
              ["Conflicts", (c: DiscoveryCard) => String(c.n_conflicts)]] as [string, (c: DiscoveryCard) => string][]).map(([k, f]) => (
              <tr key={k} style={{ cursor: "default" }}><th scope="row">{k}</th>{cmp.map((c) => <td key={c.investigation_id}>{f(c)}</td>)}</tr>))}
          </tbody></table></div>)}
    </section>
  );
}
