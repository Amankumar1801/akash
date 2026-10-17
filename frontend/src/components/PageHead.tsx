import type { ReactNode } from "react";

/** Shared page opening: a mono eyebrow, an editorial headline (the part in `accent` is set in
 *  the amber italic), and the page's own explanation underneath. */
export function PageHead({ eyebrow, title, accent, children }:
  { eyebrow: string; title: string; accent: string; children?: ReactNode }) {
  return (
    <header className="pagehead">
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title} <em>{accent}</em></h1>
      {children && <p className="prose">{children}</p>}
    </header>
  );
}
