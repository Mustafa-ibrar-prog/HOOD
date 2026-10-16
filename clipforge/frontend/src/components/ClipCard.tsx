import { useEffect, useState } from "react";
import { api, ApiError, urls } from "../api";
import { PLATFORM_LABELS, SCORE_DIMENSIONS, type Clip, type Job, type RenderOptions } from "../types";
import { CONTENT_TYPE_EMOJI, copyText, fmtTime, parseTime, scoreTone, sourceLink } from "../util";
import { CaptionEditor } from "./CaptionEditor";
import { StyleEditor } from "./StyleEditor";

type Panel = null | "timing" | "style";

export function ClipCard({ job, clip, onJob }: { job: Job; clip: Clip; onJob: (j: Job) => void }) {
  const [panel, setPanel] = useState<Panel>(null);
  const [captionsOpen, setCaptionsOpen] = useState(false);
  const [platform, setPlatform] = useState("youtube_shorts");
  const [showScores, setShowScores] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [startStr, setStartStr] = useState(fmtTime(clip.start, true));
  const [endStr, setEndStr] = useState(fmtTime(clip.end, true));
  const [style, setStyle] = useState<RenderOptions>(clip.render);

  useEffect(() => {
    setStartStr(fmtTime(clip.start, true));
    setEndStr(fmtTime(clip.end, true));
    setStyle(clip.render);
  }, [clip.start, clip.end, clip.render]);

  const duration = clip.end - clip.start;
  const working = clip.status === "pending" || clip.status === "rendering";
  const tone = scoreTone(clip.score);
  const copy = clip.platforms[platform];
  const start = parseTime(startStr);
  const end = parseTime(endStr);
  const editDur = start != null && end != null ? end - start : NaN;
  const timingError =
    start == null || end == null
      ? "Use m:ss or seconds"
      : editDur <= 1
        ? "End must be after start"
        : editDur > 60
          ? `Too long (${editDur.toFixed(1)}s > 60s)`
          : job.source?.duration && end > job.source.duration + 0.05
            ? "Past end of video"
            : null;

  async function run(fn: () => Promise<Job | void>) {
    setBusy(true);
    setErr(null);
    try {
      const j = await fn();
      if (j) onJob(j);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const nudge = (which: "start" | "end", delta: number) => {
    const v = (which === "start" ? start : end) ?? 0;
    const next = Math.max(0, v + delta);
    which === "start" ? setStartStr(fmtTime(next, true)) : setEndStr(fmtTime(next, true));
  };

  async function doCopy(label: string, text: string) {
    if (await copyText(text)) {
      setCopied(label);
      setTimeout(() => setCopied(null), 1400);
    }
  }

  const link = sourceLink(job.source?.url, clip.start);

  return (
    <article className={`clip-card ${clip.status}`}>
      <div className="player">
        {clip.status === "ready" && clip.file ? (
          <video
            key={clip.version}
            src={urls.clipVideo(job.id, clip)}
            poster={clip.thumbnail ? urls.clipThumb(job.id, clip) : undefined}
            controls
            playsInline
            preload="none"
          />
        ) : (
          <div className="placeholder">
            {working ? (
              <>
                <div className="spinner" />
                <span>{clip.status === "pending" ? "Queued for rendering…" : "Rendering…"}</span>
              </>
            ) : (
              <span className="bad">Render failed</span>
            )}
          </div>
        )}
        <div className={`rank-badge ${tone}`}>
          <span className="rank">#{clip.rank}</span>
          <span className="score">{Math.round(clip.score)}</span>
        </div>
      </div>

      <div className="body">
        <div className="meta-row">
          <span className="tag">
            {CONTENT_TYPE_EMOJI[clip.content_type] ?? "🎬"} {clip.content_type}
          </span>
          <span className="tag mono">{duration.toFixed(1)}s</span>
          <span className="tag mono" title="Position in the source video">
            {link ? (
              <a href={link} target="_blank" rel="noreferrer">
                {fmtTime(clip.start)}–{fmtTime(clip.end)} ↗
              </a>
            ) : (
              <>
                {fmtTime(clip.start)}–{fmtTime(clip.end)}
              </>
            )}
          </span>
          {clip.layout_used && <span className="tag subtle">{clip.layout_used.replace("_", " ")}</span>}
        </div>

        <blockquote className="hook">“{clip.hook}”</blockquote>
        <p className="explanation">{clip.explanation}</p>
        <p className="reason">
          <b>Why selected:</b> {clip.selection_reason}
        </p>
        {clip.error && <div className={`alert ${clip.status === "failed" ? "error" : "warn"} small`}>{clip.error}</div>}

        <button className="link small" onClick={() => setShowScores((s) => !s)}>
          {showScores ? "▾" : "▸"} Score breakdown <span className="muted">(heuristic estimate, not a view prediction)</span>
        </button>
        {showScores && (
          <div className="scores">
            {SCORE_DIMENSIONS.map((d) => {
              const v = clip.breakdown[d.key];
              return (
                <div className="score-row" key={d.key}>
                  <span className="lbl">
                    {d.label} <span className="muted">{d.weight}%</span>
                  </span>
                  <div className="bar">
                    <div className={`fill ${scoreTone(v)}`} style={{ width: `${v}%` }} />
                  </div>
                  <span className="mono val">{Math.round(v)}</span>
                </div>
              );
            })}
            <div className="muted small">Analyzed by {clip.analyzer}</div>
          </div>
        )}

        <div className="platforms">
          <div className="tabs">
            {Object.keys(PLATFORM_LABELS).map((p) => (
              <button key={p} className={p === platform ? "on" : ""} onClick={() => setPlatform(p)}>
                {PLATFORM_LABELS[p]}
              </button>
            ))}
          </div>
          {copy && (
            <div className="copy-block">
              <div className="copy-line">
                <span className="lbl">Title</span>
                <span className="val">{copy.title}</span>
                <button className="icon" title="Copy" onClick={() => doCopy("title", copy.title)}>
                  {copied === "title" ? "✓" : "⧉"}
                </button>
              </div>
              <div className="copy-line">
                <span className="lbl">Description</span>
                <span className="val">{copy.description}</span>
                <button className="icon" title="Copy" onClick={() => doCopy("desc", `${copy.description}\n\n${copy.hashtags.join(" ")}`)}>
                  {copied === "desc" ? "✓" : "⧉"}
                </button>
              </div>
              <div className="hashtags">
                {copy.hashtags.map((h) => (
                  <span key={h}>{h}</span>
                ))}
              </div>
            </div>
          )}
        </div>

        {panel === "timing" && (
          <div className="edit-panel">
            <div className="timing">
              <label>
                <span>Start</span>
                <div className="nudge">
                  <button onClick={() => nudge("start", -0.5)}>−½s</button>
                  <input value={startStr} onChange={(e) => setStartStr(e.target.value)} />
                  <button onClick={() => nudge("start", 0.5)}>+½s</button>
                </div>
              </label>
              <label>
                <span>End</span>
                <div className="nudge">
                  <button onClick={() => nudge("end", -0.5)}>−½s</button>
                  <input value={endStr} onChange={(e) => setEndStr(e.target.value)} />
                  <button onClick={() => nudge("end", 0.5)}>+½s</button>
                </div>
              </label>
            </div>
            <div className={`hint ${timingError ? "bad" : "ok"}`}>{timingError ?? `New length ${editDur.toFixed(1)}s · captions are rebuilt from the transcript`}</div>
            <div className="row-actions">
              <button className="btn ghost" onClick={() => setPanel(null)}>
                Cancel
              </button>
              <button
                className="btn primary"
                disabled={!!timingError || busy}
                onClick={() => run(() => api.updateClip(job.id, clip.id, { start: start!, end: end! })).then(() => setPanel(null))}
              >
                Apply & re-render
              </button>
            </div>
          </div>
        )}

        {panel === "style" && (
          <div className="edit-panel">
            <StyleEditor value={style} onChange={setStyle} compact />
            <div className="row-actions">
              <button className="btn ghost" onClick={() => setPanel(null)}>
                Cancel
              </button>
              <button className="btn primary" disabled={busy} onClick={() => run(() => api.updateClip(job.id, clip.id, { render: style })).then(() => setPanel(null))}>
                Apply & re-render
              </button>
            </div>
          </div>
        )}

        {err && <div className="alert error small">{err}</div>}

        <div className="actions">
          <a
            className={`btn primary ${clip.status !== "ready" ? "disabled" : ""}`}
            href={clip.status === "ready" ? urls.clipVideo(job.id, clip, true) : undefined}
            aria-disabled={clip.status !== "ready"}
          >
            ⬇ MP4
          </a>
          <button className="btn ghost" disabled={working} onClick={() => setPanel(panel === "timing" ? null : "timing")}>
            Trim
          </button>
          <button className="btn ghost" disabled={working} onClick={() => setCaptionsOpen(true)}>
            Subtitles
          </button>
          <button className="btn ghost" disabled={working} onClick={() => setPanel(panel === "style" ? null : "style")}>
            Style
          </button>
          <button className="btn ghost" disabled={working || busy} title="Re-render this clip" onClick={() => run(() => api.regenerateClip(job.id, clip.id))}>
            ↻
          </button>
          <button
            className="btn ghost danger"
            disabled={busy || clip.status === "rendering"}
            title="Delete clip"
            onClick={() => confirm("Delete this clip?") && run(() => api.deleteClip(job.id, clip.id))}
          >
            🗑
          </button>
        </div>
      </div>

      {captionsOpen && (
        <CaptionEditor
          captions={clip.captions}
          duration={duration}
          onClose={() => setCaptionsOpen(false)}
          onSave={(c) => {
            setCaptionsOpen(false);
            run(() => api.updateClip(job.id, clip.id, { captions: c }));
          }}
        />
      )}
    </article>
  );
}
