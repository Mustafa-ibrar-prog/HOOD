import { useEffect, useMemo, useState } from "react";
import { api, ApiError, urls } from "../api";
import type { Job } from "../types";
import { CONTENT_TYPE_EMOJI, fmtTime } from "../util";
import { ClipCard } from "./ClipCard";

const STAGES: { key: string; label: string }[] = [
  { key: "fetching_metadata", label: "Video info" },
  { key: "downloading", label: "Download" },
  { key: "transcribing", label: "Transcript" },
  { key: "analyzing", label: "Find moments" },
  { key: "rendering", label: "Render clips" },
  { key: "done", label: "Done" },
];

type Sort = "score" | "timeline" | "shortest" | "longest";
type DurFilter = "all" | "short" | "mid" | "long";

export function JobPage({ jobId, navigate }: { jobId: string; navigate: (p: string) => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>("score");
  const [dur, setDur] = useState<DurFilter>("all");
  const [types, setTypes] = useState<Set<string>>(new Set());
  const [minScore, setMinScore] = useState(0);
  const [thumbOk, setThumbOk] = useState(true);

  const active =
    !job || job.status === "queued" || job.status === "running" || job.clips.some((c) => c.status === "pending" || c.status === "rendering");

  useEffect(() => {
    let stop = false;
    let t: number;
    const tick = async () => {
      try {
        const j = await api.getJob(jobId);
        if (stop) return;
        setJob(j);
        setError(null);
      } catch (e) {
        if (!stop) setError(e instanceof ApiError ? e.message : String(e));
      }
    };
    tick();
    if (active) t = window.setInterval(tick, 1500);
    return () => {
      stop = true;
      window.clearInterval(t);
    };
  }, [jobId, active]);

  const contentTypes = useMemo(() => Array.from(new Set(job?.clips.map((c) => c.content_type) ?? [])).sort(), [job]);

  const clips = useMemo(() => {
    if (!job) return [];
    let cs = job.clips.filter((c) => c.score >= minScore);
    if (types.size) cs = cs.filter((c) => types.has(c.content_type));
    const d = (c: (typeof cs)[number]) => c.end - c.start;
    if (dur === "short") cs = cs.filter((c) => d(c) < 20);
    if (dur === "mid") cs = cs.filter((c) => d(c) >= 20 && d(c) <= 45);
    if (dur === "long") cs = cs.filter((c) => d(c) > 45);
    const sorted = [...cs];
    if (sort === "score") sorted.sort((a, b) => b.score - a.score);
    if (sort === "timeline") sorted.sort((a, b) => a.start - b.start);
    if (sort === "shortest") sorted.sort((a, b) => d(a) - d(b));
    if (sort === "longest") sorted.sort((a, b) => d(b) - d(a));
    return sorted;
  }, [job, sort, dur, types, minScore]);

  if (error && !job)
    return (
      <div className="center-msg">
        <div className="alert error">{error}</div>
        <button className="btn ghost" onClick={() => navigate("/")}>
          ← Back
        </button>
      </div>
    );
  if (!job)
    return (
      <div className="center-msg">
        <div className="spinner" />
      </div>
    );

  const stageIdx = job.status === "completed" ? STAGES.length - 1 : Math.max(0, STAGES.findIndex((s) => s.key === job.stage));
  const ready = job.clips.filter((c) => c.status === "ready").length;
  const toggleType = (t: string) =>
    setTypes((prev) => {
      const n = new Set(prev);
      n.has(t) ? n.delete(t) : n.add(t);
      return n;
    });

  return (
    <div className="job-page">
      <button className="link back" onClick={() => navigate("/")}>
        ← New video
      </button>

      {job.is_demo && (
        <div className="alert demo">
          <b>Demo mode.</b> This project uses a locally generated <b>sample video</b> (a labelled test card with no real footage or speech
          audio) and a <b>scripted sample transcript</b>. Moment detection, scoring, captioning and rendering run for real on that sample —
          no real video was downloaded or transcribed.
        </div>
      )}

      <header className="source">
        <div className="thumb">
          {thumbOk ? (
            <img
              src={job.source?.thumbnail_url && !job.is_demo ? job.source.thumbnail_url : urls.sourceThumb(job.id)}
              alt=""
              onError={() => setThumbOk(false)}
            />
          ) : (
            <div className="thumb-ph">▶</div>
          )}
        </div>
        <div className="info">
          <h2>{job.source?.title || job.request_url}</h2>
          <div className="muted">
            {job.source?.channel && <span>{job.source.channel} · </span>}
            {job.source?.duration ? <span>{fmtTime(job.source.duration)} · </span> : null}
            {job.source?.url?.startsWith("http") ? (
              <a href={job.source.url} target="_blank" rel="noreferrer">
                Open source ↗
              </a>
            ) : (
              <span>{job.request_url}</span>
            )}
          </div>
          <div className="chips">
            {job.transcript_source && <span className="tag subtle">Transcript: {job.transcript_source.replace(/_/g, " ")}</span>}
            {job.analyzer && <span className="tag subtle">Moments: {job.analyzer}</span>}
          </div>
        </div>
        <div className="head-actions">
          {ready > 0 && (
            <a className="btn primary" href={urls.zip(job.id)}>
              ⬇ Download all ({ready}) .zip
            </a>
          )}
          {(job.status === "running" || job.status === "queued") && (
            <button className="btn ghost" onClick={() => api.cancelJob(job.id).then(setJob)}>
              Cancel
            </button>
          )}
          <button
            className="btn ghost danger"
            title="Delete this project and all its files"
            onClick={() => confirm("Delete this project and its files?") && api.deleteJob(job.id).then(() => navigate("/"))}
          >
            Delete
          </button>
        </div>
      </header>

      {(job.status === "running" || job.status === "queued") && (
        <section className="progress-card">
          <ol className="stepper">
            {STAGES.map((s, i) => (
              <li key={s.key} className={i < stageIdx ? "done" : i === stageIdx ? "now" : ""}>
                <span className="bullet">{i < stageIdx ? "✓" : i + 1}</span>
                {s.label}
              </li>
            ))}
          </ol>
          <div className="progress">
            <div className="fill" style={{ width: `${job.progress}%` }} />
          </div>
          <div className="progress-msg">
            <span>{job.message}</span>
            <span className="mono">{Math.round(job.progress)}%</span>
          </div>
        </section>
      )}

      {job.status === "failed" && (
        <div className="alert error big">
          <b>Couldn't finish this video.</b> {job.error}
          <div className="row-actions">
            <button className="btn ghost" onClick={() => api.retryJob(job.id).then((j) => navigate(`/jobs/${j.id}`))}>
              Retry
            </button>
          </div>
        </div>
      )}
      {job.status === "cancelled" && <div className="alert warn">This job was cancelled.</div>}
      {job.warnings.map((w) => (
        <div className="alert warn small" key={w}>
          {w}
        </div>
      ))}

      {job.clips.length > 0 && (
        <>
          <div className="toolbar">
            <div className="group">
              <span className="lbl">Sort</span>
              <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                <option value="score">Highest score</option>
                <option value="timeline">Video order</option>
                <option value="shortest">Shortest</option>
                <option value="longest">Longest</option>
              </select>
            </div>
            <div className="group">
              <span className="lbl">Length</span>
              <div className="seg small">
                {(
                  [
                    ["all", "All"],
                    ["short", "<20s"],
                    ["mid", "20–45s"],
                    ["long", ">45s"],
                  ] as [DurFilter, string][]
                ).map(([k, l]) => (
                  <button key={k} className={dur === k ? "on" : ""} onClick={() => setDur(k)}>
                    {l}
                  </button>
                ))}
              </div>
            </div>
            <div className="group">
              <span className="lbl">Min score · {minScore}</span>
              <input type="range" min={0} max={90} step={5} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} />
            </div>
            <div className="group types">
              {contentTypes.map((t) => (
                <button key={t} className={`chip ${types.has(t) ? "on" : ""}`} onClick={() => toggleType(t)}>
                  {CONTENT_TYPE_EMOJI[t] ?? "🎬"} {t}
                </button>
              ))}
            </div>
          </div>
          <p className="muted small disclaimer">
            Scores are transparent heuristic estimates of hook strength, clarity, payoff and pacing — not guarantees of views or
            virality.
          </p>
          <div className="clip-grid">
            {clips.map((c) => (
              <ClipCard key={c.id} job={job} clip={c} onJob={setJob} />
            ))}
            {clips.length === 0 && <div className="muted">No clips match these filters.</div>}
          </div>
        </>
      )}
    </div>
  );
}
