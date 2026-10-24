import { useEffect, useSyncExternalStore } from "react";

/** Counts real in-flight investigative work (a submitted investigation, a running pipeline, a lab
 *  run). The logo animates only while the count is above zero, so the animation can never
 *  outlive, or precede, the work it represents. */
let n = 0;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
export const useBusyCount = (): number =>
  useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => n, () => 0);

/** Marks work in flight while `active` is true; releases on change and on unmount. */
export function useActivity(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    n += 1; emit();
    return () => { n -= 1; emit(); };
  }, [active]);
}
