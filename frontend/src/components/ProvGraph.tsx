import { useMemo, useState } from "react";
import type { ProvGraph as G, ProvNode } from "../api/types";
import { short } from "../lib/format";

const NW = 200, NH = 54, GX = 70, GY = 18;

/** Edges point from a derived thing to what it came from. Layer 0 is the raw source. */
export function layout(g: G): { pos: Map<string, { x: number; y: number; layer: number }>; w: number; h: number } {
  const to = new Map<string, string[]>();
  for (const n of g.nodes) to.set(n.prov_id, []);
  for (const e of g.edges) to.get(e.from_prov)?.push(e.to_prov);
  const memo = new Map<string, number>();
  const layerOf = (id: string, seen = new Set<string>()): number => {
    if (memo.has(id)) return memo.get(id) as number;
    if (seen.has(id)) return 0; // a cycle should not exist; do not loop forever if it does
    seen.add(id);
    const parents = to.get(id) ?? [];
    const l = parents.length ? 1 + Math.max(...parents.map((p) => layerOf(p, seen))) : 0;
    memo.set(id, l);
    return l;
  };
  const cols = new Map<number, string[]>();
  for (const n of g.nodes) { const l = layerOf(n.prov_id); cols.set(l, [...(cols.get(l) ?? []), n.prov_id]); }
  const pos = new Map<string, { x: number; y: number; layer: number }>();
  let maxRows = 1;
  for (const [l, ids] of cols) { maxRows = Math.max(maxRows, ids.length); ids.forEach((id, i) => pos.set(id, { x: 20 + l * (NW + GX), y: 20 + i * (NH + GY), layer: l })); }
  const nl = Math.max(0, ...cols.keys()) + 1;
  return { pos, w: 40 + nl * NW + (nl - 1) * GX, h: 40 + maxRows * NH + (maxRows - 1) * GY };
}

export function ProvGraphView({ g }: { g: G }) {
  const [sel, setSel] = useState<string | null>(null);
  const { pos, w, h } = useMemo(() => layout(g), [g]);
  const node = g.nodes.find((n) => n.prov_id === sel) ?? null;
  return (
    <div className="prov">
      <div>
        <p style={{ marginBottom: 10 }}>
          <span className="badge">{g.roots_verifiable ? "Every hash chain verified" : "Some chains could not be verified"}</span>
        </p>
        <div className="scroll-x"><svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="group" aria-label="Provenance graph: raw sources on the left, derived results on the right">
          {g.edges.map((e) => {
            const a = pos.get(e.from_prov), b = pos.get(e.to_prov);
            if (!a || !b) return null;
            const x1 = a.x, y1 = a.y + NH / 2, x2 = b.x + NW, y2 = b.y + NH / 2, mx = (x1 + x2) / 2;
            return <path key={`${e.from_prov}${e.to_prov}`} className="edge" d={`M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`} />;
          })}
          {g.nodes.map((n) => {
            const p = pos.get(n.prov_id);
            if (!p) return null;
            return (
              <g key={n.prov_id} className="node" transform={`translate(${p.x} ${p.y})`} role="button" tabIndex={0}
                aria-pressed={n.prov_id === sel} onClick={() => setSel(n.prov_id === sel ? null : n.prov_id)}
                onKeyDown={(k) => { if (k.key === "Enter" || k.key === " ") setSel(n.prov_id); }}>
                <rect width={NW} height={NH} rx="7" />
                <text x="12" y="22">{n.activity.replace(/_/g, " ")}</text>
                <text className="sub" x="12" y="40">{n.dataset ?? n.entity_type.replace(/_/g, " ")}{n.sha256 ? `  ${short(n.sha256, 7)}` : ""}</text>
              </g>
            );
          })}
        </svg></div>
      </div>
      <aside aria-live="polite">
        {node ? <NodeDetail n={node} /> : <p className="note" style={{ marginTop: 40 }}>Select a step to see its code version, hash and origin. Raw archive data sits on the left. Each step to the right was derived from the one before it.</p>}
      </aside>
    </div>
  );
}

function NodeDetail({ n }: { n: ProvNode }) {
  return (
    <div>
      <h3 style={{ fontSize: 20, marginBottom: 12 }}>{n.activity.replace(/_/g, " ")}</h3>
      <dl className="dl">
        <dt>Kind</dt><dd>{n.entity_type.replace(/_/g, " ")}</dd>
        <dt>Code</dt><dd>{n.code_version}</dd>
        {n.dataset && <><dt>Dataset</dt><dd>{n.dataset}{n.release ? `, ${n.release}` : ""}</dd></>}
        {n.source_uri && <><dt>Origin</dt><dd className="hash">{n.source_uri}</dd></>}
        {n.sha256 && <><dt>SHA-256</dt><dd className="hash">{n.sha256}</dd></>}
        <dt>Recorded</dt><dd>{new Date(n.at).toLocaleString()}</dd>
      </dl>
    </div>
  );
}
