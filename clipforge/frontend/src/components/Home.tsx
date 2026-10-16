import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { DEFAULT_OPTIONS, type JobOptions, type JobSummary, type PublicConfig } from "../types";
import { StyleEditor } from "./StyleEditor";

const YT_RE = /^(https?:\/\/)?((www|m|music)\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)\//i;

export function Home({ config, navigate }: { config: PublicConfig | null; navigate: (path: string) => void }) {
  const [url, setUrl] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [options, setOptions] = useState<JobOptions>(() => {
    try {
      const saved = localStorage.getItem("clipforge.options");
      return saved ? { ...DEFAULT_OPTIONS, ...JSON.parse(saved) } : DEFAULT_OPTIONS;
    } catch {
      return DEFAULT_OPTIONS;
    }
  });
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [validation, setValidation] = useState<{ ok: boolean; msg: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const timer = useRef<number>();

  useEffect(() => {
    api.listJobs().then(setJobs).catch(() => {});
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem("clipforge.options", JSON.stringify(options));
    } catch {
      /* storage unavailable */
    }
  }, [options]);

  useEffect(() => {
    window.clearTimeout(timer.current);
    setError(null);
    if (!url.trim()) return setValidation(null);
    timer.current = window.setTimeout(async () => {
      try {
        const v = await api.validate(url);
        setValidation(v.valid ? { ok: true, msg: v.kind === "short" ? "YouTube Short detected" : "YouTube video detected" } : { ok: false, msg: v.error || "Invalid URL" });
      } catch {
        setValidation(YT_RE.test(url) ? null : { ok: false, msg: "Paste a YouTube video URL" });
      }
    }, 350);
  }, [url]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!authorized) return setError("Please confirm you own this video or have permission to use it.");
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.createJob(url.trim(), authorized, options);
      navigate(`/jobs/${job.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function demo() {
    setSubmitting(true);
    try {
      const job = await api.createDemo({ ...options, max_clips: Math.min(options.max_clips, 4) });
      navigate(`/jobs/${job.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id: string) {
    await api.deleteJob(id).catch(() => {});
    setJobs((j) => j.filter((x) => x.id !== id));
  }

  return (
    <div className="home">
      <section className="hero">
        <h1>
          Turn long videos into <span className="grad">scroll-stopping shorts</span>
        </h1>
        <p className="sub">
          Paste a YouTube link. ClipForge transcribes it, finds the moments most likely to hold attention, and renders ranked,
          captioned 9:16 clips ready for Shorts, TikTok and Reels.
        </p>

        <form className="url-card" onSubmit={submit}>
          <div className={`url-row ${validation ? (validation.ok ? "valid" : "invalid") : ""}`}>
            <input
              autoFocus
              type="text"
              inputMode="url"
              placeholder="https://www.youtube.com/watch?v=…  ·  youtu.be/…  ·  youtube.com/shorts/…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              aria-label="Video URL"
            />
            <button className="btn primary big" disabled={submitting || !url.trim() || validation?.ok === false}>
              {submitting ? "Starting…" : "Generate clips"}
            </button>
          </div>
          {validation && <div className={`hint ${validation.ok ? "ok" : "bad"}`}>{validation.msg}</div>}
          <label className="check auth">
            <input type="checkbox" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} />
            <span>
              I own this video or am authorised to download and repurpose it. ClipForge only processes publicly accessible
              videos and never bypasses DRM, logins or other access controls.
            </span>
          </label>
          {error && <div className="alert error">{error}</div>}

          <div className="form-footer">
            <button type="button" className="link" onClick={() => setShowAdvanced((s) => !s)}>
              {showAdvanced ? "▾" : "▸"} Clip & caption settings
            </button>
            <button type="button" className="btn ghost" onClick={demo} disabled={submitting}>
              Try the labelled demo (no API keys needed)
            </button>
          </div>

          {showAdvanced && (
            <div className="advanced">
              <div className="grid3">
                <label>
                  <span>Max clips · {options.max_clips}</span>
                  <input type="range" min={1} max={15} value={options.max_clips} onChange={(e) => setOptions({ ...options, max_clips: Number(e.target.value) })} />
                </label>
                <label>
                  <span>Min length · {options.min_clip_seconds}s</span>
                  <input
                    type="range"
                    min={8}
                    max={40}
                    value={options.min_clip_seconds}
                    onChange={(e) => setOptions({ ...options, min_clip_seconds: Number(e.target.value) })}
                  />
                </label>
                <label>
                  <span>Max length · {options.max_clip_seconds}s</span>
                  <input
                    type="range"
                    min={Math.max(20, options.min_clip_seconds + 5)}
                    max={60}
                    value={options.max_clip_seconds}
                    onChange={(e) => setOptions({ ...options, max_clip_seconds: Number(e.target.value) })}
                  />
                </label>
              </div>
              <StyleEditor value={options.render} onChange={(render) => setOptions({ ...options, render })} />
              <button type="button" className="link small" onClick={() => setOptions(DEFAULT_OPTIONS)}>
                Reset to defaults
              </button>
            </div>
          )}
        </form>

        {config && (
          <div className="engine-note">
            Moment detection:{" "}
            <b>{config.analysis_provider === "heuristic" ? "built-in transparent heuristics" : `${config.analysis_provider} · ${config.analysis_model}`}</b>
            {config.analysis_provider === "heuristic" && <span> — add an ANTHROPIC_API_KEY or OPENAI_API_KEY on the server for LLM analysis.</span>}
          </div>
        )}
      </section>

      {jobs.length > 0 && (
        <section className="recent">
          <h2>Recent projects</h2>
          <ul>
            {jobs.map((j) => (
              <li key={j.id}>
                <a href={`#/jobs/${j.id}`}>
                  <span className={`dot ${j.status}`} />
                  <span className="t">{j.title}</span>
                  {j.is_demo && <span className="tag demo">DEMO</span>}
                </a>
                <span className="meta">
                  {j.status === "running" || j.status === "queued" ? `${Math.round(j.progress)}%` : j.status === "completed" ? `${j.clips} clips` : j.status}
                </span>
                <span className="meta">{new Date(j.created_at * 1000).toLocaleString()}</span>
                <button className="icon" title="Delete project and files" onClick={() => remove(j.id)}>
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
