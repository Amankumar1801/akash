/** The AKASH loading language. Render these only while a request is genuinely in flight.
 *  - Loader (default): an orbit with a travelling marker, for a section that is loading.
 *  - Loader variant="inline": the same orbit, smaller, for a table or card list.
 *  - Spinner: a tiny orbit for inside a button. */
export function Loader({ label = "Loading", variant = "block" }: { label?: string; variant?: "block" | "inline" }) {
  const s = variant === "inline" ? 22 : 34;
  return (
    <div className={`loader ${variant}`} role="status" aria-live="polite">
      <svg width={s} height={s} viewBox="0 0 34 34" aria-hidden="true">
        <circle cx="17" cy="17" r="12" fill="none" stroke="var(--rule)" strokeWidth="1.4" />
        <g className="loader-orbit"><circle cx="17" cy="5" r="2.6" fill="var(--lamp)" /></g>
        <path d="M17 12.6l.9 3.5 3.5.9-3.5.9-.9 3.5-.9-3.5-3.5-.9 3.5-.9z" fill="var(--ink)" />
      </svg>
      <span>{label}</span>
    </div>
  );
}

export function Spinner() {
  return (
    <svg className="spinner" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <circle cx="7" cy="7" r="5.2" fill="none" stroke="currentColor" strokeOpacity=".28" strokeWidth="1.6" />
      <path d="M7 1.8a5.2 5.2 0 0 1 5.2 5.2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
