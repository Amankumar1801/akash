/** The AKASH mark: an amber orbit ring cut by a vertical axis, with a four-point stellar glint at
 *  its centre and a small marker on the orbit. Pure SVG geometry, colours come from design tokens
 *  so it follows the red-lamp theme. */
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg className="logo-mark" width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="lg-axis" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--ink)" stopOpacity="0" />
          <stop offset="0.28" stopColor="var(--ink)" stopOpacity="0.9" />
          <stop offset="0.72" stopColor="var(--ink)" stopOpacity="0.9" />
          <stop offset="1" stopColor="var(--ink)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <circle cx="20" cy="20" r="14.5" fill="none" stroke="var(--lamp)" strokeWidth="2.2" strokeLinecap="round"
        strokeDasharray="78 13.1" transform="rotate(-62 20 20)" />
      <line x1="20" y1="1.5" x2="20" y2="38.5" stroke="url(#lg-axis)" strokeWidth="1.3" />
      <path d="M20 11.2l1.5 6.9 6.9 1.9-6.9 1.9L20 28.8l-1.5-6.9-6.9-1.9 6.9-1.9z" fill="var(--ink)" />
      <circle cx="31.6" cy="9.9" r="1.9" fill="var(--lamp)" />
    </svg>
  );
}

export function Logo({ size = 32 }: { size?: number }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      <span className="wordmark">AKASH</span>
    </span>
  );
}
