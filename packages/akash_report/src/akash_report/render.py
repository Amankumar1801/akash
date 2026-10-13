"""Markdown and HTML renderers. HTML escapes everything and carries no script or remote asset."""

from __future__ import annotations

import html
import re

from .model import Report

LABEL = {"fact": "Measured or catalogued", "prediction": "Model output",
         "interpretation": "Interpretation", "uncertainty": "Uncertainty",
         "limitation": "Limitation", "followup": "Follow-up", "note": ""}
_MD = re.compile(r"([\\`*_{}\[\]<>#|~])")


def _md(s: str) -> str:
    return _MD.sub(r"\\\1", s).replace("\n", " ")


def _cites(ids: list[str]) -> str:
    return " " + " ".join(f"[{i[:8]}]" for i in ids) if ids else ""


def to_markdown(r: Report) -> str:
    out = [f"# Investigation report: {_md(r.object_name)}", "",
           f"> {r.disclaimer}", "",
           f"Investigation `{r.investigation_id}` · pipeline `{_md(r.pipeline_version)}` · "
           f"generated {r.generated_at} · content hash `{r.content_sha256[:16]}`", ""]
    for s in r.sections:
        out += [f"## {s.number}. {_md(s.title)}", ""]
        for b in s.blocks:
            lab = LABEL[b.kind]
            by = f", written by {_md(b.author)}" if b.author else ""
            head = f"**{lab}{by}.** " if lab else ""
            out.append(f"- {head}{_md(b.text)}{_cites(b.evidence_ids)}")
        if s.id == "provenance":
            out += ["", "| Evidence | Channel | Source | Dataset | Release | Produced by | Hash |",
                    "|---|---|---|---|---|---|---|"]
            for p in r.provenance:
                out.append("| " + " | ".join(_md(x or "-") for x in (
                    p.evidence_id[:8], p.channel, p.source, p.dataset, p.release, p.produced_by,
                    p.sha256_prefix)) + " |")
        out.append("")
    if r.withheld:
        out.append(f"_{r.withheld} statement(s) were withheld because their wording asserted "
                   "more than AKASH allows._")
    return "\n".join(out) + "\n"


CSS = ("body{font:16px/1.55 Georgia,serif;max-width:46rem;margin:2rem auto;padding:0 1rem;"
       "color:#1b1b1f}h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:2rem;border-bottom:1px "
       "solid #ccc}.d{border-left:4px solid #b8860b;padding:.4rem .8rem;background:#faf5e6}"
       ".k{font:600 .72rem system-ui;text-transform:uppercase;letter-spacing:.06em;color:#555}"
       "table{border-collapse:collapse;font:.8rem system-ui;width:100%}td,th{border:1px solid #ccc;"
       "padding:3px 6px;text-align:left;overflow-wrap:anywhere}code{font-size:.85em}"
       "@media print{body{margin:0}}")


def to_html(r: Report) -> str:
    e = html.escape
    p = ["<!doctype html><html lang=en><head><meta charset=utf-8>",
         "<meta name=viewport content='width=device-width,initial-scale=1'>",
         f"<title>Report: {e(r.object_name)}</title><style>{CSS}</style></head><body>",
         f"<h1>Investigation report: {e(r.object_name)}</h1>",
         f"<p class=d>{e(r.disclaimer)}</p>",
         f"<p><small>Investigation <code>{e(r.investigation_id)}</code> · pipeline "
         f"<code>{e(r.pipeline_version)}</code> · generated {e(r.generated_at)} · content hash "
         f"<code>{e(r.content_sha256[:16])}</code></small></p>"]
    for s in r.sections:
        p.append(f"<h2>{s.number}. {e(s.title)}</h2><ul>")
        for b in s.blocks:
            lab = LABEL[b.kind] + (f", written by {b.author}" if b.author else "")
            cites = " ".join(f"<code>{e(i[:8])}</code>" for i in b.evidence_ids)
            p.append("<li>" + (f"<span class=k>{e(lab)}</span> " if LABEL[b.kind] else "")
                     + f"{e(b.text)} {cites}</li>")
        p.append("</ul>")
        if s.id == "provenance":
            p.append("<table><tr><th>Evidence<th>Channel<th>Source<th>Dataset<th>Release"
                     "<th>Produced by<th>Hash")
            for x in r.provenance:
                p.append("<tr>" + "".join(f"<td>{e(v or '-')}" for v in (
                    x.evidence_id[:8], x.channel, x.source, x.dataset, x.release, x.produced_by,
                    x.sha256_prefix)))
            p.append("</table>")
    if r.withheld:
        p.append(f"<p><em>{r.withheld} statement(s) were withheld because their wording asserted "
                 "more than AKASH allows.</em></p>")
    p.append("</body></html>")
    return "".join(p)
