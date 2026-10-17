/** Branded loading indicator: a small orbit with a travelling marker. Render it only while a
 *  request is genuinely in flight. */
export function Loader({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loader" role="status" aria-live="polite">
      <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
        <circle cx="17" cy="17" r="12" fill="none" stroke="var(--rule)" strokeWidth="1.4" />
        <g className="loader-orbit"><circle cx="17" cy="5" r="2.6" fill="var(--lamp)" /></g>
        <path d="M17 12.6l.9 3.5 3.5.9-3.5.9-.9 3.5-.9-3.5-3.5-.9 3.5-.9z" fill="var(--ink)" />
      </svg>
      <span>{label}</span>
    </div>
  );
}
