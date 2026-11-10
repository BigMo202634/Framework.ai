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
