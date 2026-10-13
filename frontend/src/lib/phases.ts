import { PHASES, type JobEvent, type Phase, type PhaseStatus } from "../api/types";

export type LaneState = "pending" | "running" | "done" | "skipped" | "failed";
export interface Lane { phase: Phase; state: LaneState; message: string }

/** Fold the ordered event log into one state per pipeline phase. */
export function reduceLanes(events: JobEvent[]): Lane[] {
  const lanes: Record<string, Lane> = Object.fromEntries(
    PHASES.map((p) => [p, { phase: p, state: "pending" as LaneState, message: "" }]));
  for (const e of events) {
    if (e.kind !== "phase") continue;
    const phase = e.data.phase as Phase, status = e.data.status as PhaseStatus;
    const lane = lanes[phase];
    if (!lane) continue; // a phase this client does not know: ignore rather than crash
    lane.state = status === "started" ? "running" : status === "completed" ? "done" : status;
    if (typeof e.data.message === "string" && e.data.message) lane.message = e.data.message;
  }
  return PHASES.map((p) => lanes[p]);
}

export function phaseDone(events: JobEvent[], phase: Phase): boolean {
  return reduceLanes(events).find((l) => l.phase === phase)?.state === "done";
}
