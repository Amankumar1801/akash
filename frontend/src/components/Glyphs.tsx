import type { Direction, VetStatus } from "../api/types";

const COLOR: Record<Direction, string> = {
  supports: "var(--supports)", contradicts: "var(--contradicts)", neutral: "var(--neutral)",
  inconclusive: "var(--neutral)",
};

/** Direction is carried by shape as well as colour: circle, diamond, bar, ring. */
export function DirGlyph({ d, size = 14 }: { d: Direction; size?: number }) {
  const c = COLOR[d];
  return (
    <svg className="glyph" width={size} height={size} viewBox="0 0 14 14" aria-hidden="true">
      {d === "supports" && <circle cx="7" cy="7" r="5.2" fill={c} />}
      {d === "contradicts" && <rect x="2.6" y="2.6" width="8.8" height="8.8" fill={c} transform="rotate(45 7 7)" />}
      {d === "neutral" && <rect x="1.5" y="5.6" width="11" height="2.8" rx="1.2" fill={c} />}
      {d === "inconclusive" && <circle cx="7" cy="7" r="4.6" fill="none" stroke={c} strokeWidth="1.8" />}
    </svg>
  );
}

const VCOLOR: Record<VetStatus, string> = {
  pass: "var(--supports)", warn: "var(--warn)", fail: "var(--contradicts)", unknown: "var(--neutral)",
};
export function VetGlyph({ s }: { s: VetStatus }) {
  const c = VCOLOR[s];
  return (
    <svg className="glyph" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      {s === "pass" && <><circle cx="8" cy="8" r="6.6" fill="none" stroke={c} strokeWidth="1.6" /><path d="M5 8.2l2.2 2.2L11 5.8" fill="none" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></>}
      {s === "warn" && <path d="M8 2.2L14.2 13H1.8z" fill="none" stroke={c} strokeWidth="1.6" strokeLinejoin="round" />}
      {s === "fail" && <><rect x="1.8" y="1.8" width="12.4" height="12.4" rx="2" fill="none" stroke={c} strokeWidth="1.6" /><path d="M5.2 5.2l5.6 5.6M10.8 5.2l-5.6 5.6" stroke={c} strokeWidth="1.8" strokeLinecap="round" /></>}
      {s === "unknown" && <circle cx="8" cy="8" r="6.2" fill="none" stroke={c} strokeWidth="1.6" strokeDasharray="2.6 2.4" />}
    </svg>
  );
}

export function Mark() {
  return (
    <svg viewBox="0 0 30 18" aria-hidden="true">
      <path d="M1 6h8l2.4 9.4L15 6h14" fill="none" stroke="var(--lamp)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
