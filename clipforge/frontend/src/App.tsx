import { useEffect, useState } from "react";
import { api } from "./api";
import { Home } from "./components/Home";
import { JobPage } from "./components/JobPage";
import type { PublicConfig } from "./types";

function useHashRoute(): [string, (p: string) => void] {
  const get = () => window.location.hash.replace(/^#/, "") || "/";
  const [route, setRoute] = useState(get);
  useEffect(() => {
    const on = () => setRoute(get());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [route, (p: string) => (window.location.hash = p)];
}

export default function App() {
  const [route, navigate] = useHashRoute();
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api
      .config()
      .then((c) => {
        setConfig(c);
        setOffline(false);
      })
      .catch(() => setOffline(true));
  }, []);

  const jobMatch = route.match(/^\/jobs\/([a-f0-9]+)$/);

  return (
    <div className="app">
      <nav className="topbar">
        <a className="brand" href="#/">
          <span className="logo">▶</span> ClipForge
        </a>
        <span className="spacer" />
        {config && (
          <span className="engine" title="Configured on the server">
            <span className={`dot ${config.analysis_provider === "heuristic" ? "idle" : "completed"}`} />
            {config.analysis_provider === "heuristic" ? "Heuristic mode" : `AI: ${config.analysis_model}`}
          </span>
        )}
      </nav>
      {offline && <div className="alert error banner">Can't reach the ClipForge API. Start the backend (see README) and reload.</div>}
      <main>{jobMatch ? <JobPage key={jobMatch[1]} jobId={jobMatch[1]} navigate={navigate} /> : <Home config={config} navigate={navigate} />}</main>
      <footer className="foot">
        Process only content you own or are authorised to use. Clip scores are estimates, not predictions of views.
      </footer>
    </div>
  );
}
