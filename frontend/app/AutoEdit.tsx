"use client";

import { useEffect, useRef, useState } from "react";
import {
  exportUrl,
  getJob,
  planEdit,
  startRender,
  type Aspect,
  type EditRequest,
  type Job,
  type MediaSummary,
  type PlanResponse,
} from "@/lib/api";

const ASPECTS: { value: Aspect; label: string }[] = [
  { value: "9:16", label: "9:16 Reels / TikTok" },
  { value: "16:9", label: "16:9 YouTube" },
  { value: "1:1", label: "1:1 Square" },
  { value: "4:5", label: "4:5 Feed" },
  { value: "source", label: "Keep original" },
];

export default function AutoEdit({ media }: { media: MediaSummary }) {
  const [req, setReq] = useState<EditRequest>({
    aspect: "9:16",
    remove_silences: true,
    punch_ins: true,
  });
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current);
  }, []);

  async function preview() {
    setError(null);
    setBusy(true);
    try {
      setPlan(await planEdit(media.media_id, req));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function render() {
    setError(null);
    setBusy(true);
    try {
      const j = await startRender(media.media_id, req);
      setJob(j);
      timer.current = setInterval(async () => {
        try {
          const next = await getJob(j.job_id);
          setJob(next);
          if (next.status === "done" || next.status === "failed") {
            if (timer.current) clearInterval(timer.current);
            setBusy(false);
            if (next.status === "failed") setError(next.error ?? "Render failed");
          }
        } catch (e) {
          if (timer.current) clearInterval(timer.current);
          setBusy(false);
          setError(e instanceof Error ? e.message : String(e));
        }
      }, 700);
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const removed = plan ? plan.source_duration_s - plan.plan.segments.reduce((t, s) => t + s.src_out - s.src_in, 0) : 0;

  return (
    <section className="mt-10 rounded-xl border border-neutral-800 p-5">
      <h2 className="text-xl font-semibold">Auto edit</h2>
      <p className="mt-1 text-sm text-neutral-400">Cuts the silences, adds punch-ins on jump cuts, and reframes for your platform.</p>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
        <select
          className="rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2"
          value={req.aspect}
          onChange={(e) => setReq({ ...req, aspect: e.target.value as Aspect })}
          disabled={busy}
        >
          {ASPECTS.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={req.remove_silences} disabled={busy}
            onChange={(e) => setReq({ ...req, remove_silences: e.target.checked })} />
          Remove silences
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={req.punch_ins} disabled={busy}
            onChange={(e) => setReq({ ...req, punch_ins: e.target.checked })} />
          Punch-ins
        </label>
      </div>

      <div className="mt-4 flex gap-3">
        <button onClick={preview} disabled={busy}
          className="rounded-md border border-neutral-600 px-4 py-2 text-sm hover:bg-neutral-800 disabled:opacity-50">
          Preview plan
        </button>
        <button onClick={render} disabled={busy}
          className="rounded-md bg-white px-4 py-2 text-sm font-medium text-black hover:bg-neutral-200 disabled:opacity-50">
          Edit my video
        </button>
      </div>

      {error && <p className="mt-4 rounded-lg bg-red-950 px-4 py-3 text-sm text-red-200">{error}</p>}

      {plan && (
        <div className="mt-5 text-sm">
          <p>{plan.plan.summary}</p>
          <p className="text-neutral-400">
            {media.duration_s.toFixed(1)}s → {(media.duration_s - removed).toFixed(1)}s · {plan.plan.segments.length} cuts · brain: {plan.plan.brain}
          </p>
          {plan.validation.warnings.map((w) => (
            <p key={w} className="text-amber-300">⚠ {w}</p>
          ))}
          {/* Simple timeline strip: kept parts in white, removed parts dark */}
          <div className="relative mt-3 h-6 w-full overflow-hidden rounded bg-neutral-800">
            {plan.plan.segments.map((s, i) => (
              <div key={i} title={`${s.src_in.toFixed(2)}–${s.src_out.toFixed(2)}s ${s.reason}`}
                className={`absolute top-0 h-full ${s.zoom > 1 ? "bg-sky-300" : "bg-white"}`}
                style={{
                  left: `${(s.src_in / plan.source_duration_s) * 100}%`,
                  width: `${((s.src_out - s.src_in) / plan.source_duration_s) * 100}%`,
                }} />
            ))}
          </div>
          <p className="mt-1 text-xs text-neutral-500">White: kept · Blue: kept with punch-in · Grey: removed</p>
        </div>
      )}

      {job && job.status !== "done" && job.status !== "failed" && (
        <div className="mt-5">
          <div className="h-2 w-full overflow-hidden rounded bg-neutral-800">
            <div className="h-full bg-white transition-all" style={{ width: `${Math.round(job.progress * 100)}%` }} />
          </div>
          <p className="mt-2 text-sm text-neutral-400">{job.message || "Queued"}</p>
        </div>
      )}

      {job?.status === "done" && job.output && (
        <div className="mt-5">
          <video src={exportUrl(job)} controls className="max-h-[70vh] w-full rounded-lg bg-black" />
          <a href={exportUrl(job)} download className="mt-3 inline-block rounded-md bg-white px-4 py-2 text-sm font-medium text-black">
            Download MP4
          </a>
        </div>
      )}
    </section>
  );
}
