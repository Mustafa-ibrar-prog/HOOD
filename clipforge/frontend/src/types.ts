export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ClipStatus = "pending" | "rendering" | "ready" | "failed";
export type Layout = "auto" | "face_track" | "center" | "blur" | "gaming";

export interface Word {
  start: number;
  end: number;
  text: string;
}

export interface CaptionLine {
  start: number;
  end: number;
  text: string;
  words: Word[];
}

export interface CaptionStyle {
  enabled: boolean;
  font: string;
  font_size: number;
  primary_color: string;
  highlight_color: string;
  outline_color: string;
  outline_width: number;
  position: "bottom" | "middle" | "top";
  uppercase: boolean;
  words_per_caption: number;
  highlight_active_word: boolean;
}

export interface RenderOptions {
  layout: Layout;
  crop_x: number;
  captions: CaptionStyle;
}

export interface JobOptions {
  max_clips: number;
  min_clip_seconds: number;
  max_clip_seconds: number;
  render: RenderOptions;
}

export interface ScoreBreakdown {
  hook: number;
  emotion: number;
  clarity: number;
  payoff: number;
  pacing: number;
  shareability: number;
}

export interface PlatformCopy {
  title: string;
  description: string;
  hashtags: string[];
}

export interface Clip {
  id: string;
  rank: number;
  start: number;
  end: number;
  score: number;
  breakdown: ScoreBreakdown;
  content_type: string;
  hook: string;
  explanation: string;
  selection_reason: string;
  transcript: string;
  captions: CaptionLine[];
  platforms: Record<string, PlatformCopy>;
  render: RenderOptions;
  status: ClipStatus;
  error: string | null;
  layout_used: string | null;
  file: string | null;
  thumbnail: string | null;
  output_width: number | null;
  output_height: number | null;
  rendered_duration: number | null;
  analyzer: string;
  version: number;
}

export interface SourceInfo {
  provider: string;
  url: string;
  video_id: string | null;
  title: string;
  channel: string | null;
  duration: number | null;
  thumbnail_url: string | null;
  width: number | null;
  height: number | null;
  is_sample: boolean;
}

export interface Job {
  id: string;
  status: JobStatus;
  stage: string;
  progress: number;
  message: string;
  error: string | null;
  error_code: string | null;
  created_at: number;
  updated_at: number;
  request_url: string;
  options: JobOptions;
  source: SourceInfo | null;
  transcript_source: string | null;
  analyzer: string | null;
  warnings: string[];
  clips: Clip[];
  is_demo: boolean;
}

export interface JobSummary {
  id: string;
  status: JobStatus;
  progress: number;
  stage: string;
  created_at: number;
  title: string;
  clips: number;
  is_demo: boolean;
}

export interface PublicConfig {
  analysis_provider: string;
  analysis_model: string;
  transcription_provider: string;
  has_anthropic_key: boolean;
  has_openai_key: boolean;
  max_clip_seconds: number;
  max_video_seconds: number;
  default_max_clips: number;
  storage_backend: string;
}

export const DEFAULT_CAPTION_STYLE: CaptionStyle = {
  enabled: true,
  font: "Inter",
  font_size: 78,
  primary_color: "#FFFFFF",
  highlight_color: "#FFD400",
  outline_color: "#000000",
  outline_width: 5,
  position: "bottom",
  uppercase: false,
  words_per_caption: 3,
  highlight_active_word: true,
};

export const DEFAULT_OPTIONS: JobOptions = {
  max_clips: 8,
  min_clip_seconds: 15,
  max_clip_seconds: 60,
  render: { layout: "auto", crop_x: 0.5, captions: DEFAULT_CAPTION_STYLE },
};

export const SCORE_DIMENSIONS: { key: keyof ScoreBreakdown; label: string; weight: number }[] = [
  { key: "hook", label: "Opening hook", weight: 25 },
  { key: "emotion", label: "Emotion / entertainment", weight: 20 },
  { key: "clarity", label: "Standalone clarity", weight: 20 },
  { key: "payoff", label: "Payoff & completeness", weight: 15 },
  { key: "pacing", label: "Pacing & retention", weight: 10 },
  { key: "shareability", label: "Shareability", weight: 10 },
];

export const PLATFORM_LABELS: Record<string, string> = {
  youtube_shorts: "YouTube Shorts",
  tiktok: "TikTok",
  instagram_reels: "Instagram Reels",
};
