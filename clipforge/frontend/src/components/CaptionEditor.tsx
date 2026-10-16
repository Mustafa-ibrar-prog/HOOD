import { useState } from "react";
import type { CaptionLine } from "../types";
import { fmtTime } from "../util";

export function CaptionEditor({
  captions,
  duration,
  onSave,
  onClose,
}: {
  captions: CaptionLine[];
  duration: number;
  onSave: (c: CaptionLine[]) => void;
  onClose: () => void;
}) {
  const [lines, setLines] = useState<CaptionLine[]>(() => captions.map((c) => ({ ...c })));
  const update = (i: number, patch: Partial<CaptionLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const remove = (i: number) => setLines((ls) => ls.filter((_, j) => j !== i));
  const add = () => {
    const last = lines[lines.length - 1];
    const start = last ? Math.min(last.end, duration - 0.5) : 0;
    setLines([...lines, { start, end: Math.min(start + 1.5, duration), text: "New caption", words: [] }]);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Edit subtitles">
        <header>
          <h3>Edit subtitles</h3>
          <button className="icon" onClick={onClose}>
            ✕
          </button>
        </header>
        <p className="muted small">
          Times are relative to the clip start ({fmtTime(duration, true)} long). Editing text keeps timing; word highlight timing is
          redistributed if you change the number of words.
        </p>
        <div className="caption-list">
          {lines.map((l, i) => (
            <div className="caption-row" key={i}>
              <input
                className="time"
                type="number"
                step={0.1}
                min={0}
                max={duration}
                value={l.start}
                onChange={(e) => update(i, { start: Number(e.target.value) })}
              />
              <input
                className="time"
                type="number"
                step={0.1}
                min={0}
                max={duration}
                value={l.end}
                onChange={(e) => update(i, { end: Number(e.target.value) })}
              />
              <input className="text" value={l.text} onChange={(e) => update(i, { text: e.target.value })} />
              <button className="icon" title="Remove" onClick={() => remove(i)}>
                ✕
              </button>
            </div>
          ))}
        </div>
        <footer>
          <button className="btn ghost" onClick={add}>
            + Add caption
          </button>
          <span className="spacer" />
          <button className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn primary"
            onClick={() => onSave(lines.filter((l) => l.text.trim() && l.end > l.start).sort((a, b) => a.start - b.start))}
          >
            Save & re-render
          </button>
        </footer>
      </div>
    </div>
  );
}
