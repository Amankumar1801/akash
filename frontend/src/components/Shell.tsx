import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import { Logo } from "./Logo";
import { SpaceBackground } from "./SpaceBackground";

const I = { fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round", strokeLinejoin: "round" } as const;
const ICONS: Record<string, JSX.Element> = {
  logbook: <><rect x="4" y="3.5" width="12" height="13" rx="1.5" /><path d="M7.5 7.5h5M7.5 10.5h5M7.5 13.5h3" /></>,
  candidates: <><circle cx="10" cy="10" r="2.2" /><circle cx="10" cy="10" r="6.5" strokeDasharray="2.4 2.6" /></>,
  sky: <><circle cx="10" cy="10" r="6.8" /><ellipse cx="10" cy="10" rx="3" ry="6.8" /><path d="M3.2 10h13.6" /></>,
  spectra: <path d="M2.5 13l2.4-4 2 3.2 2.3-7 2.2 8 1.8-4 2.3 2.6" />,
  images: <><rect x="3" y="4" width="14" height="12" rx="1.5" /><circle cx="7.5" cy="8.2" r="1.3" /><path d="M3.5 14.5l4.2-3.6 3 2.4 2.6-2.2 3.2 3" /></>,
  models: <><path d="M10 3l6 3.2v6.6L10 16l-6-3.2V6.2z" /><path d="M10 9.6V16M4 6.2l6 3.4 6-3.4" /></>,
  lab: <><path d="M8 3.5h4M9 3.5v5L4.8 15a1.4 1.4 0 001.2 2h8a1.4 1.4 0 001.2-2L11 8.5v-5" /><path d="M6.6 12.5h6.8" /></>,
};
const NAV: [string, string, string, boolean][] = [
  ["/", "Logbook", "logbook", true], ["/candidates", "Candidates", "candidates", false], ["/sky", "Sky", "sky", false],
  ["/spectra", "Spectra", "spectra", false], ["/images", "Images", "images", false], ["/models", "Models", "models", false],
  ["/lab", "Lab", "lab", false],
];

function useRedLamp(): [boolean, () => void] {
  const [red, setRed] = useState(() => {
    try { return localStorage.getItem("akash.theme") === "red"; } catch { return false; }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = red ? "red" : "night";
    try { localStorage.setItem("akash.theme", red ? "red" : "night"); } catch { /* ignore */ }
  }, [red]);
  return [red, () => setRed((r) => !r)];
}

export function Shell({ children }: { children: ReactNode }) {
  const { settings, update } = useApi();
  const [red, toggleRed] = useRedLamp();
  const dlg = useRef<HTMLDialogElement>(null);
  const [test, setTest] = useState<string>("");
  const [draft, setDraft] = useState(settings);
  const demo = settings.mode === "demo";

  const open = () => { setDraft(settings); setTest(""); dlg.current?.showModal(); };
  const save = () => { update(draft); dlg.current?.close(); };
  const check = async () => {
    setTest("Checking...");
    try {
      const { HttpApi } = await import("../api/client");
      const me = await new HttpApi(draft.baseUrl.replace(/\/$/, ""), draft.apiKey).me();
      setTest(`Connected as ${me.name} (${me.role}).`);
    } catch (e) { setTest(explain(e)); }
  };

  const { pathname } = useLocation();
  return (
    <>
      <SpaceBackground />
      <div className="app">
        <aside className="side">
          <NavLink to="/" className="brand" aria-label="Akash home"><Logo size={34} /></NavLink>
          <nav className="nav" aria-label="Main">
            {NAV.map(([to, label, icon, end]) => (
              <NavLink key={to} to={to} end={end}>
                <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false" {...I}>{ICONS[icon]}</svg>
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
        </aside>
        <div className="stage">
          <header className="bar">
            <span className="tagline" aria-hidden="true">Explore the unseen</span>
            <span className="grow" />
            <button className="chip" onClick={toggleRed} aria-pressed={red} title="Red light keeps your eyes dark-adapted at the telescope">
              <span>{red ? "Red lamp on" : <>Red<span className="hide-s"> lamp</span></>}</span>
            </button>
            <button className={`chip ${demo ? "" : "live"}`} onClick={open} aria-label="Open settings">
              <span className="dot" /><span>{demo ? <>Demo<span className="hide-s"> data</span></> : "Live API"}</span>
            </button>
          </header>
          {demo && (
            <div className="demo-banner" role="note">
              <b>Demo data.</b> Everything here is synthetic and generated in your browser. The star IDs do not exist in any archive.
              Switch to a live API in settings.
            </div>
          )}
          <main key={pathname} className="route">{children}</main>
          <footer className="foot">
            <b>Akash assists investigation. It does not establish discoveries.</b> A model output is a prediction, an anomaly is a reason to look, and a candidate is not a planet.
          </footer>
        </div>
      </div>
      <dialog ref={dlg} aria-labelledby="set-h" onClose={() => undefined}>
        <h2 id="set-h">Settings</h2>
        <div className="opt">
          <label>Data source</label>
          <div className="seg" role="group" aria-label="Data source">
            <button aria-pressed={draft.mode === "demo"} onClick={() => setDraft({ ...draft, mode: "demo" })}>Demo data</button>
            <button aria-pressed={draft.mode === "live"} onClick={() => setDraft({ ...draft, mode: "live" })}>Live API</button>
          </div>
        </div>
        {draft.mode === "live" && (
          <>
            <div className="opt"><label htmlFor="base">API address (leave empty to use this site)</label>
              <input id="base" type="text" value={draft.baseUrl} placeholder="https://api.example.org" autoComplete="off"
                onChange={(e) => setDraft({ ...draft, baseUrl: e.target.value })} /></div>
            <div className="opt"><label htmlFor="key">API key</label>
              <input id="key" type="password" value={draft.apiKey} placeholder="akash_..." autoComplete="off"
                onChange={(e) => setDraft({ ...draft, apiKey: e.target.value })} />
              <span className="muted" style={{ fontSize: 13 }}>Kept for this browser tab only. Never stored on disk.</span></div>
            <button className="btn" onClick={check}>Test connection</button>
            <p role="status" className="note">{test}</p>
          </>
        )}
        <div className="row-end">
          <button className="btn" onClick={() => dlg.current?.close()}>Cancel</button>
          <button className="btn primary" onClick={save}>Save</button>
        </div>
      </dialog>
    </>
  );
}
