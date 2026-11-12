"use client";

// /editor: upload a video, or reopen one with /editor?m=<media id>.

import Link from "next/link";
import { useEffect, useState } from "react";
import { getMedia, uploadMedia, type MediaSummary } from "@/lib/api";
import Editor from "./Editor";

export default function EditorPage() {
  const [media, setMedia] = useState<MediaSummary | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("m");
    if (!id) { setChecking(false); return; }
    getMedia(id).then(setMedia).catch(() => setError("That video isn't on this computer any more. Upload it again.")).finally(() => setChecking(false));
  }, []);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setProgress(0);
    try {
      const m = await uploadMedia(file, setProgress);
      window.history.replaceState(null, "", `/editor?m=${m.media_id}`);
      setMedia(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProgress(null);
    }
  }

  if (media) return <Editor key={media.media_id} media={media} />;

  return (
    <main className="flex min-h-screen flex-col bg-[#0d0f14] text-neutral-200">
      <header className="flex h-12 items-center border-b border-white/10 px-4 text-sm">
        <Link href="/" className="font-semibold tracking-tight text-white">FRAMEWORK <span className="text-violet-400">AI</span></Link>
      </header>
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-xl">
          <h1 className="text-2xl font-semibold text-white">Start a new edit</h1>
          <p className="mt-1 text-sm text-neutral-400">Drop in a talking video. The editor cuts it first, then you fine-tune it on the timeline.</p>
          <label className="mt-6 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-white/15 bg-white/[0.02] px-6 py-16 text-center hover:border-violet-400/60"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); void onFile(e.dataTransfer.files?.[0]); }}>
            <span className="text-lg text-white">{checking ? "Loading…" : "Drop a video here or click to choose"}</span>
            <span className="mt-1 text-sm text-neutral-500">MP4, MOV, MKV, WebM, MXF</span>
            <input type="file" accept="video/*,.mxf" className="hidden" disabled={progress !== null}
              onChange={(e) => onFile(e.target.files?.[0])} />
          </label>
          {progress !== null && (
            <div className="mt-5">
              <div className="h-1.5 w-full overflow-hidden rounded bg-white/10">
                <div className="h-full bg-violet-500 transition-all" style={{ width: `${progress}%` }} />
              </div>
              <p className="mt-2 text-sm text-neutral-400">{progress < 100 ? `Uploading ${progress}%` : "Checking the video…"}</p>
            </div>
          )}
          {error && <p className="mt-5 rounded-lg bg-red-950 px-4 py-3 text-sm text-red-200">{error}</p>}
        </div>
      </div>
    </main>
  );
}
