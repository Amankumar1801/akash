import type { Assessment, EvidenceRow } from "../api/types";
import { ruleText, TRIAGE } from "../lib/labels";
import { DirGlyph } from "./Glyphs";

export function Verdict({ a, evidence, onOpenEvidence }: {
  a: Assessment; evidence: EvidenceRow[]; onOpenEvidence: (id: string) => void;
}) {
  const t = TRIAGE[a.triage_category];
  return (
    <section className="verdict" aria-labelledby="verdict-h">
      <h2 id="verdict-h"><span className="vg"><DirGlyph d={t.tone} size={22} /></span>{t.title}</h2>
      <p className="prose">{t.gist}</p>
      <div className="why">
        <ul aria-label="Why">
          {a.triage_reasons.map((r) => (
            <li key={r.rule}>
              <span>{ruleText(r.rule)}</span>
              {(() => {
                const ids = r.evidence_ids.filter((id) => evidence.some((e) => e.evidence_id === id));
                return ids.length ? <button className="link" onClick={() => onOpenEvidence(ids[0])}>
                  {ids.length === 1 ? "see the finding" : `see ${ids.length} findings`}</button> : null;
              })()}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
