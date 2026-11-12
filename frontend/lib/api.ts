export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type MediaSummary = {
  media_id: string;
  original_name: string;
  duration_s: number;
  width: number;
  height: number;
  fps: number;
  orientation: "vertical" | "horizontal" | "square" | "unknown";
  has_audio: boolean;
  info: {
    container: string;
    size_bytes: number;
    bitrate: number | null;
    video: {
      codec: string;
      pix_fmt: string | null;
      bit_depth: number | null;
      color_transfer: string | null;
      color_primaries: string | null;
    } | null;
    audio: { codec: string; sample_rate: number; channels: number } | null;
  };
};

export type Aspect = "source" | "9:16" | "16:9" | "1:1" | "4:5";

export type EditRequest = {
  aspect: Aspect;
  remove_silences: boolean;
  punch_ins: boolean;
  creative_cuts: boolean;
};

export type Segment = { src_in: number; src_out: number; zoom: number; focus_x?: number; focus_y?: number; reason: string };

export type RemovedPart = {
  start: number;
  end: number;
  kind: "filler" | "stutter" | "retake" | "repetition" | "off_message";
  text: string;
  reason: string;
};

export type Plan = {
  version: string;
  media_id: string;
  brain: string;
  summary: string;
  message: string;
  segments: Segment[];
  removed: RemovedPart[];
  output: { aspect: Aspect; width: number | null; height: number | null; fps: number | null; crf: number; audio_bitrate_k: number };
};

export type PlanResponse = {
  plan: Plan;
  validation: { ok: boolean; errors: string[]; warnings: string[] };
  source_duration_s: number;
};

export type Job = {
  job_id: string;
  media_id: string;
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  message: string;
  error: string | null;
  output: string | null;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new Error(`Cannot reach the backend at ${API_URL}. Is it running?`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : detail?.errors
          ? `${detail.message}: ${detail.errors.join("; ")}`
          : `Request failed (HTTP ${res.status})`;
    throw new Error(msg);
  }
  return body as T;
}

export const planEdit = (mediaId: string, req: EditRequest) =>
  call<PlanResponse>(`/api/media/${mediaId}/plan`, { method: "POST", body: JSON.stringify(req) });

export const startRender = (mediaId: string, req: EditRequest, plan?: Plan) =>
  call<Job>(`/api/media/${mediaId}/render`, { method: "POST", body: JSON.stringify({ request: req, plan }) });

export type ChatResponse = {
  reply: string;
  changes: string[];
  plan: Plan;
  validation: { ok: boolean; errors: string[]; warnings: string[] };
  mode: "rules" | "claude";
};

export const sendChat = (mediaId: string, message: string, plan: Plan) =>
  call<ChatResponse>(`/api/media/${mediaId}/chat`, { method: "POST", body: JSON.stringify({ message, plan }) });

export const getMedia = (mediaId: string) => call<MediaSummary>(`/api/media/${mediaId}`);

export type Waveform = { rate: number; peaks: number[] };
export const getWaveform = (mediaId: string) => call<Waveform>(`/api/media/${mediaId}/waveform`);

export type Word = { i: number; start: number; end: number; text: string; prob: number };
export type Transcript = { model: string; language: string; words: Word[] };
export const getTranscript = (mediaId: string) => call<Transcript>(`/api/media/${mediaId}/transcript`);

export const proxyUrl = (mediaId: string) => `${API_URL}/api/media/${mediaId}/proxy.mp4`;

export const getJob = (jobId: string) => call<Job>(`/api/jobs/${jobId}`);

export const exportUrl = (job: Job) => `${API_URL}/api/media/${job.media_id}/exports/${job.output}`;

/** Upload a video with progress reporting. Uses XHR because fetch has no upload progress. */
export function uploadMedia(file: File, onProgress: (pct: number) => void): Promise<MediaSummary> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/api/media`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as MediaSummary);
      else {
        const detail = (body as { detail?: string } | null)?.detail;
        reject(new Error(detail ?? `Upload failed (HTTP ${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error(`Cannot reach the backend at ${API_URL}. Is it running?`));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
