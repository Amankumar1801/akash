import { PHASE_NAMES } from "../lib/labels";
import type { Lane } from "../lib/phases";

const W = 260, MID = 7;
function path(state: Lane["state"]): string {
  if (state === "running") {
    let d = `M0 ${MID}`;
    for (let x = 0; x < W; x += 20) d += ` q5 -6 10 0 t10 0`;
    return d;
  }
  if (state === "done") return `M0 ${MID} H108 L114 13 H146 L152 ${MID} H${W}`; // a tiny transit
  if (state === "failed") return `M0 ${MID} H80 L90 1 L104 13 L118 2 L130 ${MID} H${W}`;
  return `M0 ${MID} H${W}`;
}
const STATE_WORD: Record<Lane["state"], string> = {
  pending: "waiting", running: "running", done: "done", skipped: "skipped", failed: "failed",
};

/** One lane per phase. The trace is the status: dashed amber while running, a dip when done. */
export function Recorder({ lanes }: { lanes: Lane[] }) {
  return (
    <ol className="lanes" aria-label="Investigation progress">
      {lanes.map((l) => (
        <li key={l.phase} className={`lane ${l.state}`} aria-current={l.state === "running" ? "step" : undefined}>
          <div className="row">
            <span className="name">{PHASE_NAMES[l.phase].name}</span>
            <span className="state">{STATE_WORD[l.state]}</span>
          </div>
          <div className="msg">{l.message || (l.state === "pending" ? PHASE_NAMES[l.phase].detail : "")}</div>
          <svg className="trace" viewBox={`0 0 ${W} 14`} preserveAspectRatio="none" aria-hidden="true">
            <path d={path(l.state)} />
          </svg>
        </li>
      ))}
    </ol>
  );
}
