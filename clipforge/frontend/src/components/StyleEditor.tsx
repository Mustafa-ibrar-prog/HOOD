import type { Layout, RenderOptions } from "../types";

const LAYOUTS: { value: Layout; label: string; hint: string }[] = [
  { value: "auto", label: "Auto", hint: "Track faces when found, gaming layout for facecams, else blurred background" },
  { value: "face_track", label: "Speaker tracking", hint: "Follow the active speaker's face" },
  { value: "gaming", label: "Gaming", hint: "Full gameplay with facecam on top" },
  { value: "blur", label: "Blurred background", hint: "Whole frame over a blurred fill" },
  { value: "center", label: "Fixed crop", hint: "Static 9:16 crop at the chosen position" },
];

const FONTS = ["Inter", "DejaVu Sans", "FreeSans", "Arial", "Impact", "Montserrat"];

export function StyleEditor({ value, onChange, compact = false }: { value: RenderOptions; onChange: (v: RenderOptions) => void; compact?: boolean }) {
  const cap = value.captions;
  const setCap = (patch: Partial<RenderOptions["captions"]>) => onChange({ ...value, captions: { ...cap, ...patch } });
  return (
    <div className={`style-editor ${compact ? "compact" : ""}`}>
      <fieldset>
        <legend>Framing</legend>
        <div className="seg">
          {LAYOUTS.map((l) => (
            <button
              type="button"
              key={l.value}
              title={l.hint}
              className={value.layout === l.value ? "on" : ""}
              onClick={() => onChange({ ...value, layout: l.value })}
            >
              {l.label}
            </button>
          ))}
        </div>
        {value.layout === "center" && (
          <label className="row">
            <span>Crop position</span>
            <input type="range" min={0} max={1} step={0.01} value={value.crop_x} onChange={(e) => onChange({ ...value, crop_x: Number(e.target.value) })} />
            <span className="mono">{Math.round(value.crop_x * 100)}%</span>
          </label>
        )}
      </fieldset>

      <fieldset>
        <legend>
          <label className="check">
            <input type="checkbox" checked={cap.enabled} onChange={(e) => setCap({ enabled: e.target.checked })} /> Captions
          </label>
        </legend>
        {cap.enabled && (
          <div className="grid2">
            <label>
              <span>Font</span>
              <select value={cap.font} onChange={(e) => setCap({ font: e.target.value })}>
                {FONTS.map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Size · {cap.font_size}</span>
              <input type="range" min={40} max={130} value={cap.font_size} onChange={(e) => setCap({ font_size: Number(e.target.value) })} />
            </label>
            <label>
              <span>Text</span>
              <input type="color" value={cap.primary_color} onChange={(e) => setCap({ primary_color: e.target.value.toUpperCase() })} />
            </label>
            <label>
              <span>Highlight</span>
              <input type="color" value={cap.highlight_color} onChange={(e) => setCap({ highlight_color: e.target.value.toUpperCase() })} />
            </label>
            <label>
              <span>Outline</span>
              <input type="color" value={cap.outline_color} onChange={(e) => setCap({ outline_color: e.target.value.toUpperCase() })} />
            </label>
            <label>
              <span>Outline width · {cap.outline_width}</span>
              <input type="range" min={0} max={12} step={0.5} value={cap.outline_width} onChange={(e) => setCap({ outline_width: Number(e.target.value) })} />
            </label>
            <label>
              <span>Position</span>
              <select value={cap.position} onChange={(e) => setCap({ position: e.target.value as RenderOptions["captions"]["position"] })}>
                <option value="bottom">Lower third</option>
                <option value="middle">Middle</option>
                <option value="top">Top</option>
              </select>
            </label>
            <label>
              <span>Words per caption · {cap.words_per_caption}</span>
              <input type="range" min={1} max={6} value={cap.words_per_caption} onChange={(e) => setCap({ words_per_caption: Number(e.target.value) })} />
            </label>
            <label className="check">
              <input type="checkbox" checked={cap.uppercase} onChange={(e) => setCap({ uppercase: e.target.checked })} /> UPPERCASE
            </label>
            <label className="check">
              <input type="checkbox" checked={cap.highlight_active_word} onChange={(e) => setCap({ highlight_active_word: e.target.checked })} /> Highlight spoken word
            </label>
          </div>
        )}
        {cap.enabled && (
          <div className="caption-preview" style={{ fontFamily: cap.font }}>
            <span
              style={{
                color: cap.primary_color,
                WebkitTextStroke: `${Math.max(cap.outline_width / 3, 0)}px ${cap.outline_color}`,
                fontSize: Math.round(cap.font_size / 3.2),
                textTransform: cap.uppercase ? "uppercase" : "none",
              }}
            >
              This is <span style={{ color: cap.highlight_active_word ? cap.highlight_color : cap.primary_color }}>how</span> captions look
            </span>
          </div>
        )}
      </fieldset>
    </div>
  );
}
