import { useMemo, useState } from "react";
import type { Direction, EvidenceRow } from "../api/types";
import { renderValue, short } from "../lib/format";
import { CHANNELS, DIRECTION } from "../lib/labels";
import { DirGlyph } from "./Glyphs";

const DIRS: Direction[] = ["supports", "contradicts", "neutral", "inconclusive"];

export function EvidenceStrip({ rows, selected, onSelect }: {
  rows: EvidenceRow[]; selected: string | null; onSelect: (id: string | null) => void;
}) {
  const [filter, setFilter] = useState<Direction | "all">("all");
  const tally = useMemo(() => Object.fromEntries(DIRS.map((d) => [d, rows.filter((r) => r.agreement === d).length])), [rows]);
  const sel = rows.find((r) => r.evidence_id === selected) ?? null;
  const shown = filter === "all" ? rows : rows.filter((r) => r.agreement === filter);

  return (
    <div className="strip">
      <div className="tally" role="group" aria-label="Evidence tallies (shown separately, never summed into a score)">
        {DIRS.map((d) => (
          <button key={d} className="link" style={{ textDecoration: filter === d ? "underline" : "none" }}
            onClick={() => setFilter(filter === d ? "all" : d)} aria-pressed={filter === d}>
            <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
              <DirGlyph d={d} /><span className="num">{tally[d]}</span> {DIRECTION[d].word.toLowerCase()}
            </span>
          </button>
        ))}
      </div>
      <p className="muted" style={{ fontSize: 13.5, marginBottom: 6 }}>
        Each mark is one finding. Above the line supports a planet-scale signal, below it points away. Marks within a lane are in the order they were produced, not on a scale.
      </p>
      {CHANNELS.map((ch) => {
        const items = rows.filter((r) => r.channel === ch.id);
        return (
          <div className="lane-e" key={ch.id}>
            <div className="lab"><b>{ch.name}</b><span>{ch.blurb}</span></div>
            <div className="rec" role="group" aria-label={`${ch.name}: ${items.length} findings`}>
              {items.length === 0 && <span className="muted" style={{ fontSize: 13.5, background: "var(--night)", padding: "0 8px" }}>No findings in this channel</span>}
              {items.map((e) => (
                <button key={e.evidence_id} className="mk" data-d={e.agreement}
                  aria-pressed={e.evidence_id === selected} onClick={() => onSelect(e.evidence_id === selected ? null : e.evidence_id)}
                  aria-label={`${DIRECTION[e.agreement].word}: ${e.observation}`} title={e.observation}>
                  <svg viewBox="0 0 20 20"><g transform="translate(3 3)"><DirShape d={e.agreement} /></g></svg>
                </button>
              ))}
            </div>
          </div>
        );
      })}
      <div className="legend" aria-hidden="true">
        {DIRS.map((d) => <span key={d}><DirGlyph d={d} />{DIRECTION[d].word}</span>)}
      </div>

      {sel && <Detail row={sel} />}

      <div className="scroll-x">
        <table className="tbl">
          <caption className="visually-hidden">All evidence rows</caption>
          <thead><tr><th>Finding</th><th>Channel</th><th>Source</th><th>Reliability</th></tr></thead>
          <tbody>
            {shown.map((e) => (
              <tr key={e.evidence_id} data-sel={e.evidence_id === selected} tabIndex={0}
                onClick={() => onSelect(e.evidence_id)} onKeyDown={(k) => { if (k.key === "Enter") onSelect(e.evidence_id); }}>
                <td><span style={{ display: "inline-flex", gap: 8, alignItems: "baseline" }}><DirGlyph d={e.agreement} />{e.observation}</span></td>
                <td>{CHANNELS.find((c) => c.id === e.channel)?.name}</td>
                <td>{e.source.source}</td>
                <td>{e.reliability.replace(/_/g, " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DirShape({ d }: { d: Direction }) {
  const c = d === "supports" ? "var(--supports)" : d === "contradicts" ? "var(--contradicts)" : "var(--neutral)";
  if (d === "supports") return <circle cx="7" cy="7" r="6" fill={c} />;
  if (d === "contradicts") return <rect x="2" y="2" width="10" height="10" fill={c} transform="rotate(45 7 7)" />;
  if (d === "neutral") return <rect x="0.5" y="5.4" width="13" height="3.2" rx="1.4" fill={c} />;
  return <circle cx="7" cy="7" r="5.2" fill="none" stroke={c} strokeWidth="2" />;
}

function Detail({ row }: { row: EvidenceRow }) {
  return (
    <section className="drawer" aria-label="Evidence detail">
      <h3>{row.observation}</h3>
      <dl className="dl">
        <dt>Reads as</dt><dd>{DIRECTION[row.agreement].word}</dd>
        <dt>Value</dt><dd>{renderValue(row.result)}</dd>
        {row.uncertainty && <><dt>Uncertainty</dt><dd>{renderValue(row.uncertainty)}</dd></>}
        <dt>Reliability</dt><dd>{row.reliability.replace(/_/g, " ")}</dd>
        <dt>Made by</dt><dd>{row.created_by}, {row.version}</dd>
        <dt>When</dt><dd>{new Date(row.timestamp).toLocaleString()}</dd>
      </dl>
      <dl className="dl">
        <dt>Source</dt><dd>{row.source.source}{row.source.release ? `, ${row.source.release}` : ""}</dd>
        {row.source.uri && <><dt>Address</dt><dd className="hash">{row.source.uri}</dd></>}
        {row.source.sha256 && <><dt>Content hash</dt><dd className="hash" title={row.source.sha256}>{row.source.sha256}</dd></>}
        <dt>Provenance</dt><dd className="hash">{row.provenance_ids.map((p) => short(p)).join(", ") || "none: commentary only"}</dd>
      </dl>
    </section>
  );
}
