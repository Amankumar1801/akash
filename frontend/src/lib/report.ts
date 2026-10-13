import type { Assessment, EvidenceRow } from "../api/types";

const SECTIONS: { title: string; channels: string[]; label: string }[] = [
  { title: "Observational evidence", channels: ["observed_fact", "data_quality"], label: "Measured or catalogued" },
  { title: "ML predictions", channels: ["model_prediction"], label: "Model output" },
  { title: "Anomaly analysis", channels: ["anomaly"], label: "Model output" },
  { title: "Cross-survey evidence", channels: ["catalog_status", "cross_survey"], label: "Measured or catalogued" },
  { title: "Possible interpretations", channels: ["interpretation"], label: "Interpretation" },
];
const DISCLAIMER = "AKASH assists investigation; it does not independently establish discoveries.";
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const mdEsc = (s: string) => s.replace(/([\\`*_{}[\]<>#|~])/g, "\\$1");

/** Demo-mode report: same shape as the server's, built from the synthetic evidence. */
export function demoReport(name: string, a: Assessment | null, ev: EvidenceRow[], format: "markdown" | "html") {
  const lines: string[] = [];
  const cite = (r: EvidenceRow) => `[${r.evidence_id.slice(0, 8)}]`;
  lines.push(`# Investigation report: ${mdEsc(name)}`, "", `> ${DISCLAIMER}`, "", "> Demo data: synthetic, for illustration only.", "");
  lines.push("## 1. Object overview", "", a ? `- Triage category: ${a.triage_category.replace(/_/g, " ")}. A reason for a human to look, not a conclusion.` : "- No repeating dip stood above the noise.", "");
  SECTIONS.forEach((s, i) => {
    lines.push(`## ${i + 2}. ${s.title}`, "");
    const rows = ev.filter((r) => s.channels.includes(r.channel));
    if (!rows.length) lines.push("- Nothing was recorded for this section.");
    for (const r of rows) lines.push(`- **${s.label}.** ${mdEsc(r.observation.replace(/\.$/, ""))} ${cite(r)}`);
    lines.push("");
  });
  const conf = ev.filter((r) => r.agreement === "contradicts");
  lines.push(`## ${SECTIONS.length + 2}. Conflicting evidence`, "");
  if (!conf.length) lines.push("- No recorded evidence contradicts the supporting evidence.");
  for (const r of conf) lines.push(`- ${mdEsc(r.observation)} ${cite(r)}`);
  lines.push("", `## ${SECTIONS.length + 3}. References and data provenance`, "");
  for (const r of ev) lines.push(`- ${cite(r)} ${mdEsc(r.channel)}, ${mdEsc(r.source.dataset ?? "n/a")}, produced by ${mdEsc(r.version)}`);
  const md = lines.join("\n") + "\n";
  if (format === "markdown") return { text: md, filename: "akash-demo-report.md", mime: "text/markdown" };
  const body = lines.map((l) => (l.startsWith("## ") ? `<h2>${esc(l.slice(3))}</h2>` : l.startsWith("# ") ? `<h1>${esc(l.slice(2))}</h1>`
    : l.startsWith("- ") ? `<p>${esc(l.slice(2))}</p>` : l.startsWith("> ") ? `<p><em>${esc(l.slice(2))}</em></p>` : "")).join("");
  const html = `<!doctype html><meta charset=utf-8><title>Report: ${esc(name)}</title><body style="font:16px/1.5 Georgia,serif;max-width:46rem;margin:2rem auto">${body}</body>`;
  return { text: html, filename: "akash-demo-report.html", mime: "text/html" };
}
