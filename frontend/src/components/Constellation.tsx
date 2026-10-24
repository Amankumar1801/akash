import type { Lane } from "../lib/phases";
import { PHASE_NAMES } from "../lib/labels";

const W = 260, H = 112;
const YS = [70, 36, 78, 30, 74, 42, 72, 48];
const pts = (n: number) => YS.slice(0, n).map((y, i) => ({ x: 18 + (i * (W - 36)) / Math.max(1, n - 1), y }));

/** The pipeline drawn as a small constellation. A star lights only when its step has really
 *  finished, pulses while it runs, and stays dim and dashed if it was skipped. A line fills once
 *  the step before it is done, and carries a moving pulse while the next step is running. It
 *  repeats what the step list shows, so it is hidden from assistive technology. */
export function Constellation({ lanes }: { lanes: Lane[] }) {
  const p = pts(lanes.length);
  return (
    <svg className="constellation" viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
      {p.slice(1).map((b, i) => {
        const a = p[i], from = lanes[i], to = lanes[i + 1];
        const lit = from.state === "done" || from.state === "skipped";
        const flow = lit && to.state === "running";
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={`cs-line${lit ? " lit" : ""}${flow ? " flow" : ""}`} />;
      })}
      {p.map((a, i) => (
        <g key={lanes[i].phase} className={`cs-star ${lanes[i].state}`} transform={`translate(${a.x} ${a.y})`}>
          <title>{`${PHASE_NAMES[lanes[i].phase].name}: ${lanes[i].state}`}</title>
          <circle className="cs-halo" r="9" />
          <circle className="cs-core" r="3.4" />
        </g>
      ))}
    </svg>
  );
}
