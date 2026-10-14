import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { explain } from "../api/client";
import { useApi } from "../api/settings";
import { Mark } from "./Glyphs";

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

  return (
    <>
      <header className="bar">
        <NavLink to="/" className="mark" aria-label="Akash home"><Mark />Akash</NavLink>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>Logbook</NavLink>
          <NavLink to="/candidates">Candidates</NavLink>
          <NavLink to="/sky">Sky</NavLink>
          <NavLink to="/models">Models</NavLink>
          <NavLink to="/lab">Lab</NavLink>
        </nav>
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
      <main>{children}</main>
      <footer className="foot">
        <b>Akash assists investigation. It does not establish discoveries.</b> A model output is a prediction, an anomaly is a reason to look, and a candidate is not a planet.
      </footer>
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
