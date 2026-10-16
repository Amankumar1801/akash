import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Discoveries } from "./pages/Discoveries";
import { Home } from "./pages/Home";
import { ImageViewer } from "./pages/ImageViewer";
import { Investigation } from "./pages/Investigation";
import { Lab } from "./pages/Lab";
import { Models } from "./pages/Models";
import { SkyMap } from "./pages/SkyMap";
import { Spectra } from "./pages/Spectra";

export function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/investigations/:id" element={<Investigation />} />
        <Route path="/models" element={<Models />} />
        <Route path="/candidates" element={<Discoveries />} />
        <Route path="/sky" element={<SkyMap />} />
        <Route path="/spectra" element={<Spectra />} />
        <Route path="/images" element={<ImageViewer />} />
        <Route path="/lab" element={<Lab />} />
        <Route path="*" element={<section className="section"><h2>That page does not exist</h2><p className="prose" style={{ marginTop: 8 }}>Use the logbook to find an investigation.</p></section>} />
      </Routes>
    </Shell>
  );
}
