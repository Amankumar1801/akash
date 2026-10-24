const R = 34;  // star radius in the drawing
const BASE = 112;

/** A schematic of what the search measured: a planet-sized disc crossing a star, and the dip it
 *  makes, drawn in step. The planet's size follows sqrt(depth) and the dip's width follows the
 *  geometry; the speed of the loop is for watching only, and the dip is drawn deeper than it is.
 *  It is a diagram of the measured numbers, not a picture of the star. */
export function TransitScene({ depthPpm, durationH, periodD }: { depthPpm: number; durationH: number; periodD: number }) {
  const rp = Math.min(18, Math.max(3, R * Math.sqrt(Math.max(depthPpm, 0) / 1e6)));
  const cx = 110, dip = 16;
  const xa = cx - R - rp, xb = cx - R + rp, xc = cx + R - rp, xd = cx + R + rp;
  const d = `M8 ${BASE} H${xa} L${xb} ${BASE + dip} H${xc} L${xd} ${BASE} H212`;
  return (
    <figure className="transit-scene">
      <svg viewBox="0 0 220 140" role="img"
           aria-label={`Schematic of a planet crossing its star. Measured depth ${Math.round(depthPpm)} parts per million, lasting ${durationH.toFixed(1)} hours, repeating every ${periodD.toFixed(2)} days.`}>
        <defs>
          <radialGradient id="ts-star" cx="38%" cy="34%" r="75%">
            <stop offset="0" stopColor="var(--star-hi, #fff3c4)" /><stop offset="1" stopColor="var(--star-lo, #f2b84b)" />
          </radialGradient>
          <radialGradient id="ts-glow"><stop offset="0.55" stopColor="var(--lamp)" stopOpacity="0.28" /><stop offset="1" stopColor="var(--lamp)" stopOpacity="0" /></radialGradient>
        </defs>
        <circle cx={cx} cy="46" r={R + 16} fill="url(#ts-glow)" />
        <circle cx={cx} cy="46" r={R} fill="url(#ts-star)" />
        <circle className="ts-planet" cx={cx} cy="46" r={rp} />
        <path d={d} className="ts-curve" />
        <line className="ts-cursor" x1={cx} x2={cx} y1={BASE - 12} y2={BASE + dip + 8} />
      </svg>
      <figcaption>
        <span className="num">{Math.round(depthPpm).toLocaleString("en-US")} ppm</span> deep, <span className="num">{durationH.toFixed(1)} h</span> long,
        every <span className="num">{periodD.toFixed(2)} d</span>. <span className="muted">Schematic of the measured numbers, sped up, with the dip drawn deeper than it is. Not an image of the star.</span>
      </figcaption>
    </figure>
  );
}
