import type { AkashApi } from "../api/client";
import type { JobEvent } from "../api/types";

const TERMINAL = new Set(["job_succeeded", "job_failed", "job_cancelled"]);
export const isTerminal = (kind: string): boolean => TERMINAL.has(kind);

/**
 * Follow a job's events to the end. Reconnects from the last seen sequence number, so a dropped
 * connection loses nothing; gives up after a few consecutive failures and reports why.
 */
export async function follow(api: AkashApi, id: string, onEvent: (e: JobEvent) => void,
  signal: AbortSignal, maxRetries = 4): Promise<"done" | "aborted" | "lost"> {
  let last = 0, failures = 0;
  while (!signal.aborted) {
    try {
      for await (const e of api.events(id, last, signal)) {
        failures = 0;
        if (e.seq <= last) continue;
        last = e.seq;
        onEvent(e);
        if (isTerminal(e.kind)) return "done";
      }
      return "done"; // stream ended cleanly (server closes after the terminal event)
    } catch (err) {
      if (signal.aborted || (err instanceof DOMException && err.name === "AbortError")) return "aborted";
      if (++failures > maxRetries) return "lost";
      await new Promise((r) => setTimeout(r, Math.min(4000, 400 * 2 ** failures)));
    }
  }
  return "aborted";
}
