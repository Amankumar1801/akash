import { useState } from "react";
import { BodyArt } from "./BodyArt";

/** Page scenes: large illustrative space images behind a page's opening. They are decorative layers
 *  (the images themselves are set in styles.css, so a missing file just leaves the page plain). */
export type SceneName = "candidates" | "sky" | "models" | "lab";

export function Scene({ name }: { name: SceneName }) {
  return <div className={`scene scene-${name}`} aria-hidden="true" />;
}

const BY_SEED = ["clean-transit", "known-planet", "candidate", "false-positive", "eclipsing-binary",
  "models-split", "catalogs-down", "no-signal"] as const;
export type CaseKind = (typeof BY_SEED)[number];

/** Which illustration stands for which triage category. It encodes nothing measured: a candidate's
 *  picture is never an image of that star. */
export const KIND_BY_CATEGORY: Record<string, CaseKind> = {
  new_signal_review: "clean-transit", known_confirmed: "known-planet", known_candidate: "candidate",
  known_false_positive: "false-positive", likely_systematic: "eclipsing-binary", models_disagree: "models-split",
  insufficient_data: "catalogs-down",
};

/** A small illustration. If the file is missing the older SVG drawing is shown instead. */
export function CaseArt({ kind, seed = 0, className = "caseart" }: { kind?: CaseKind; seed?: number; className?: string }) {
  const [bad, setBad] = useState(false);
  const k = kind ?? BY_SEED[(Math.max(1, seed) - 1) % BY_SEED.length];
  if (bad) return <BodyArt seed={seed || 1} />;
  return <img className={className} src={`/assets/space/case-${k}.webp`} alt="" aria-hidden="true" width={260} height={195}
              loading="lazy" decoding="async" onError={() => setBad(true)} />;
}
