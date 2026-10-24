import type { Direction, EvidenceRow } from "../api/types";
import { CHANNELS, DIRECTION } from "../lib/labels";

const C = 170, R0 = 34, STEP = 21;

/** Evidence as rings around the target. One ring per channel; each mark on a ring is one finding,
 *  coloured by what it says (supports, points away, context, could not decide). A channel with no
 *  findings stays a dotted outline. The rings turn slowly and stop while the pointer is over them,
 *  so a mark can be picked. Nothing here is a score: the rings are the same findings as the
 *  strip below, in another arrangement. */
export function EvidenceRings({ rows, selected, onSelect }: {
  rows: EvidenceRow[]; selected: string | null; onSelect: (id: string | null) => void;
}) {
  return (
    <figure className="rings">
      <svg viewBox={`0 0 ${C * 2} ${C * 2}`} role="group" aria-label="Evidence rings, one ring per channel. The same findings are listed below.">
        <circle className="rg-core" cx={C} cy={C} r="12" />
        {CHANNELS.map((ch, ci) => {
          const items = rows.filter((r) => r.channel === ch.id);
          const r = R0 + ci * STEP;
          return (
            <g key={ch.id}>
              <circle cx={C} cy={C} r={r} className={`rg-ring${items.length ? "" : " empty"}`} />
              <g className="rg-spin" style={{ animationDuration: `${70 + ci * 23}s`, animationDirection: ci % 2 ? "reverse" : "normal" }}>
                {items.map((e, i) => {
                  const ang = (i / items.length) * Math.PI * 2 + ci * 0.7;
                  return (
                    <circle key={e.evidence_id} className={`rg-dot d-${e.agreement}${e.evidence_id === selected ? " on" : ""}`}
                      cx={C + r * Math.cos(ang)} cy={C + r * Math.sin(ang)} r="5.2" tabIndex={0} role="button"
                      aria-label={`${DIRECTION[e.agreement as Direction].word}: ${e.observation}`} aria-pressed={e.evidence_id === selected}
                      onClick={() => onSelect(e.evidence_id === selected ? null : e.evidence_id)}
                      onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onSelect(e.evidence_id === selected ? null : e.evidence_id); } }}>
                      <title>{e.observation}</title>
                    </circle>);
                })}
              </g>
            </g>);
        })}
      </svg>
      <figcaption>
        <ul>{CHANNELS.map((ch) => {
          const n = rows.filter((r) => r.channel === ch.id).length;
          return <li key={ch.id} className={n ? "" : "muted"}><b>{ch.name}</b> <span className="num">{n || "none"}</span></li>;
        })}</ul>
        <p className="muted">Inner to outer, in this order. Cyan supports a planet-scale signal, red points away, grey is context, a hollow mark could not decide.</p>
      </figcaption>
    </figure>
  );
}
