export function fmtTime(sec: number | null | undefined, withMs = false): string {
  if (sec == null || !isFinite(sec)) return "–";
  const s = Math.max(0, sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const secStr = withMs ? r.toFixed(1).padStart(4, "0") : String(Math.floor(r)).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${secStr}` : `${m}:${secStr}`;
}

/** Parse "1:02:03.5", "2:15", "75.2" into seconds. Returns null if invalid. */
export function parseTime(input: string): number | null {
  const t = input.trim();
  if (!t) return null;
  const parts = t.split(":");
  if (parts.length > 3 || parts.some((p) => p === "" || isNaN(Number(p)))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

export function scoreTone(score: number): "great" | "good" | "ok" | "weak" {
  if (score >= 75) return "great";
  if (score >= 62) return "good";
  if (score >= 50) return "ok";
  return "weak";
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function sourceLink(url: string | undefined, seconds: number): string | null {
  if (!url || !url.startsWith("http")) return null;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}t=${Math.floor(seconds)}s`;
}

export const CONTENT_TYPE_EMOJI: Record<string, string> = {
  funny: "😂",
  debate: "🔥",
  emotional: "💛",
  educational: "💡",
  gaming: "🎮",
  surprising: "🤯",
  story: "📖",
  suspense: "⏳",
  conversation: "💬",
};
