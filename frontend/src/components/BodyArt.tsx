import { rng } from "../api/demo";

/** Small deterministic celestial thumbnails for the synthetic cases: a dark limb-lit sphere in a
 *  hue chosen from the case id, optionally with a thin ring or a rim of light. Decorative only:
 *  it encodes nothing about the case. */
export function BodyArt({ seed, size = 92 }: { seed: number; size?: number }) {
  const r = rng(seed * 97 + 5);
  const hue = [38, 205, 14, 190, 28, 220, 48, 160][seed % 8];
  const ring = r() > 0.45, tilt = -25 + r() * 50, rim = 0.4 + r() * 0.5, id = `ba${seed}`;
  const c1 = `hsl(${hue} 80% 62%)`, c2 = `hsl(${(hue + 20) % 360} 70% 38%)`;
  return (
    <svg className="bodyart" width={size} height={size * 0.82} viewBox="0 0 92 76" aria-hidden="true" focusable="false">
      <defs>
        <radialGradient id={`${id}s`} cx="0.3" cy="0.3" r="0.9">
          <stop offset="0" stopColor="#0d1424" /><stop offset="0.65" stopColor="#060a14" /><stop offset="1" stopColor="#02040a" />
        </radialGradient>
        <radialGradient id={`${id}g`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0.82" stopColor={c1} stopOpacity="0" /><stop offset="0.93" stopColor={c1} stopOpacity={rim} />
          <stop offset="1" stopColor={c2} stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="46" cy="38" r="31" fill={`url(#${id}g)`} />
      <circle cx="46" cy="38" r="23" fill={`url(#${id}s)`} />
      <path d={`M${46 - 23 * Math.cos(0.9)} ${38 - 23 * Math.sin(0.9)}A23 23 0 0 1 ${46 + 23 * Math.cos(0.2)} ${38 - 23 * Math.sin(0.2)}`}
        fill="none" stroke={c1} strokeWidth="1.5" strokeOpacity={rim} strokeLinecap="round" transform={`rotate(${tilt} 46 38)`} />
      {ring && <ellipse cx="46" cy="38" rx="38" ry="8" fill="none" stroke={c1} strokeOpacity="0.55" strokeWidth="1.1"
        transform={`rotate(${tilt} 46 38)`} />}
    </svg>
  );
}
