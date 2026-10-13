import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { type AkashApi, HttpApi } from "./client";
import { DemoApi } from "./demo";

export interface Settings { mode: "live" | "demo"; baseUrl: string; apiKey: string }
const DEFAULTS: Settings = {
  mode: import.meta.env.VITE_DEFAULT_MODE === "live" ? "live" : "demo",
  baseUrl: import.meta.env.VITE_API_URL ?? "", apiKey: "",
};

function load(): Settings {
  try {
    const raw = sessionStorage.getItem("akash.settings"); // session only: a key should not outlive the tab
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Settings>) } : DEFAULTS;
  } catch { return DEFAULTS; }
}

interface Ctx { settings: Settings; api: AkashApi; update: (s: Partial<Settings>) => void }
const C = createContext<Ctx | null>(null);
const demo = new DemoApi(); // one instance, so demo investigations persist across pages

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, set] = useState<Settings>(load);
  const api = useMemo<AkashApi>(
    () => (settings.mode === "demo" ? demo : new HttpApi(settings.baseUrl.replace(/\/$/, ""), settings.apiKey)),
    [settings]);
  const update = (s: Partial<Settings>) => {
    const next = { ...settings, ...s };
    try { sessionStorage.setItem("akash.settings", JSON.stringify(next)); } catch { /* private mode */ }
    set(next);
  };
  return <C.Provider value={{ settings, api, update }}>{children}</C.Provider>;
}
export function useApi(): Ctx {
  const c = useContext(C);
  if (!c) throw new Error("SettingsProvider missing");
  return c;
}
