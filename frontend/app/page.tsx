"use client";

import { useState } from "react";
import { uploadMedia, type MediaSummary } from "@/lib/api";

function formatBytes(n: number) {
  if (n > 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  return `${(n / 1e6).toFixed(1)} MB`;
}

export default function Home() {
  const [progress, setProgress] = useState<number | null>(null);
  const [media, setMedia] = useState<MediaSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setMedia(null);
    setProgress(0);
    try {
      setMedia(await uploadMedia(file, setProgress));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProgress(null);
    }
  }

  const v = media?.info.video;
  const rows: [string, string][] = media
    ? [
        ["File", media.original_name],
        ["Duration", `${media.duration_s.toFixed(2)} s`],
        ["Resolution", `${media.width} × ${media.height} (${media.orientation})`],
        ["Frame rate", `${media.fps} fps`],
        ["Video codec", `${v?.codec ?? "?"}${v?.bit_depth ? `, ${v.bit_depth}-bit` : ""}${v?.pix_fmt ? `, ${v.pix_fmt}` : ""}`],
        ["Colour tags", `${v?.color_primaries ?? "untagged"} / ${v?.color_transfer ?? "untagged"}`],
        ["Audio", media.info.audio ? `${media.info.audio.codec}, ${media.info.audio.sample_rate} Hz, ${media.info.audio.channels} ch` : "none"],
        ["Container", media.info.container],
        ["Size", formatBytes(media.info.size_bytes)],
      ]
    : [];

  return (
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-3xl font-semibold tracking-tight">FRAMEWORK AI</h1>
      <p className="mt-2 text-neutral-400">v0.1 · Import a talking-head video to inspect it.</p>

      <label className="mt-8 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-neutral-700 px-6 py-12 text-center hover:border-neutral-500">
        <span className="text-lg">Drop a video here or click to choose</span>
        <span className="mt-1 text-sm text-neutral-500">MP4, MOV, MKV, WebM, MXF</span>
        <input
          type="file"
          accept="video/*,.mxf"
          className="hidden"
          disabled={progress !== null}
          onChange={(e) => onFile(e.target.files?.[0])}
        />
      </label>

      {progress !== null && (
        <div className="mt-6">
          <div className="h-2 w-full overflow-hidden rounded bg-neutral-800">
            <div className="h-full bg-white transition-all" style={{ width: `${progress}%` }} />
          </div>
          <p className="mt-2 text-sm text-neutral-400">{progress < 100 ? `Uploading ${progress}%` : "Inspecting…"}</p>
        </div>
      )}

      {error && <p className="mt-6 rounded-lg bg-red-950 px-4 py-3 text-red-200">{error}</p>}

      {media && (
        <table className="mt-8 w-full text-left text-sm">
          <tbody>
            {rows.map(([k, val]) => (
              <tr key={k} className="border-b border-neutral-800">
                <th className="py-2 pr-4 font-normal text-neutral-400">{k}</th>
                <td className="py-2">{val}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
