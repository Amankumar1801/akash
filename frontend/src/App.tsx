import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Home } from "./pages/Home";
import { Investigation } from "./pages/Investigation";
import { Models } from "./pages/Models";

export function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/investigations/:id" element={<Investigation />} />
        <Route path="/models" element={<Models />} />
        <Route path="*" element={<section className="section"><h2>That page does not exist</h2><p className="prose" style={{ marginTop: 8 }}>Use the logbook to find an investigation.</p></section>} />
      </Routes>
    </Shell>
  );
}
