"use client";

import { useEffect, useRef, useState } from "react";
import {
  exportUrl,
  getJob,
  planEdit,
  sendChat,
  startRender,
  type Aspect,
  type EditRequest,
  type Job,
  type MediaSummary,
  type Plan,
} from "@/lib/api";

const ASPECTS: { value: Aspect; label: string }[] = [
  { value: "9:16", label: "9:16 Reels / TikTok" },
  { value: "16:9", label: "16:9 YouTube" },
  { value: "1:1", label: "1:1 Square" },
  { value: "4:5", label: "4:5 Feed" },
  { value: "source", label: "Keep original" },
];

type Msg = { from: "you" | "editor"; text: string };

const KIND_LABEL: Record<string, string> = {
  filler: "Filler",
  stutter: "Stutter",
  retake: "False start",
  repetition: "Said twice",
  off_message: "Off message",
};

const dur = (p: Plan) => p.segments.reduce((t, s) => t + s.src_out - s.src_in, 0);
const fmt = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

export default function AutoEdit({ media }: { media: MediaSummary }) {
  const [req, setReq] = useState<EditRequest>({ aspect: "9:16", remove_silences: true, punch_ins: true, creative_cuts: true });
  const [plan, setPlan] = useState<Plan | null>(null);
  const [history, setHistory] = useState<Plan[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const chatEnd = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current);
  }, []);
  useEffect(() => {
    // Braces matter: newer browsers return a Promise from scrollIntoView, and React would
    // treat a returned value as a cleanup function and crash.
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  async function makePlan() {
    setError(null);
    setBusy(true);
    try {
      const r = await planEdit(media.media_id, req);
      setPlan(r.plan);
      setHistory([]);
      setWarnings(r.validation.warnings);
      setMessages([{ from: "editor", text: `${r.plan.summary} Tell me what to change, e.g. "cut 0:05 to 0:09" or "make it tighter".` }]);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function chat() {
    const text = draft.trim();
    if (!text || !plan) return;
    setDraft("");
    setMessages((m) => [...m, { from: "you", text }]);
    if (/^\s*undo\b/i.test(text)) return undo();
    setBusy(true);
    try {
      const r = await sendChat(media.media_id, text, plan);
      setMode(r.mode);
      if (r.changes.length) {
        setHistory((h) => [...h, plan]);
        setPlan(r.plan);
        setReq((q) => ({ ...q, aspect: r.plan.output.aspect }));
      }
      setWarnings(r.validation.warnings);
      setMessages((m) => [...m, { from: "editor", text: r.reply }]);
    } catch (e) {
      setMessages((m) => [...m, { from: "editor", text: `Something went wrong: ${e instanceof Error ? e.message : e}` }]);
    } finally {
      setBusy(false);
    }
  }

  function undo() {
    setHistory((h) => {
      if (!h.length) {
        setMessages((m) => [...m, { from: "editor", text: "Nothing to undo." }]);
        return h;
      }
      setPlan(h[h.length - 1]);
      setMessages((m) => [...m, { from: "editor", text: "Undone." }]);
      return h.slice(0, -1);
    });
  }

  async function render() {
    if (!plan) return;
    setError(null);
    setBusy(true);
    try {
      const j = await startRender(media.media_id, req, plan);
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
          fail(e);
        }
      }, 700);
    } catch (e) {
      setBusy(false);
      fail(e);
    }
  }

  const total = plan ? dur(plan) : 0;
  let cursor = 0;

  return (
    <section className="mt-10 rounded-xl border border-neutral-800 p-5">
      <h2 className="text-xl font-semibold">Auto edit</h2>
      <p className="mt-1 text-sm text-neutral-400">Cuts the silences, adds punch-ins on jump cuts, and reframes for your platform. Then talk to the editor to adjust.</p>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
        <select className="rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2" value={req.aspect} disabled={busy}
          onChange={(e) => setReq({ ...req, aspect: e.target.value as Aspect })}>
          {ASPECTS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
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
        <label className="flex items-center gap-2" title="Reads what you said and cuts um, uh, em, stutters, false starts and lines said twice">
          <input type="checkbox" checked={req.creative_cuts} disabled={busy}
            onChange={(e) => setReq({ ...req, creative_cuts: e.target.checked })} />
          Cut fillers &amp; repeats
        </label>
        <button onClick={makePlan} disabled={busy}
          className="rounded-md border border-neutral-600 px-4 py-2 hover:bg-neutral-800 disabled:opacity-50">
          {plan ? "Start over" : "Create edit"}
        </button>
      </div>

      {busy && !plan && req.creative_cuts && (
        <p className="mt-4 text-sm text-neutral-400">Listening to your video and reading the transcript. The first time takes a minute or two.</p>
      )}

      {error && <p className="mt-4 rounded-lg bg-red-950 px-4 py-3 text-sm text-red-200">{error}</p>}

      {plan && (
        <>
          {/* Edited timeline: what the viewer will see, in order. Times here are what the chat uses. */}
          <div className="mt-6">
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium">Timeline</span>
              <span className="text-neutral-400">
                {fmt(total)} edited · {plan.segments.length} parts · format {plan.output.aspect} · {media.duration_s.toFixed(1)}s original
              </span>
            </div>
            <div className="relative mt-2 flex h-10 w-full overflow-hidden rounded bg-neutral-900">
              {plan.segments.map((s, i) => {
                const start = cursor;
                cursor += s.src_out - s.src_in;
                return (
                  <div key={i} title={`${fmt(start)}–${fmt(cursor)} · source ${s.src_in.toFixed(1)}–${s.src_out.toFixed(1)}s${s.zoom > 1 ? ` · zoom ${s.zoom}` : ""}`}
                    className={`h-full border-r border-neutral-950 ${s.zoom > 1 ? "bg-sky-400" : "bg-neutral-200"}`}
                    style={{ width: `${((s.src_out - s.src_in) / total) * 100}%` }} />
                );
              })}
            </div>
            <div className="mt-1 flex justify-between text-xs text-neutral-500">
              {[0, 0.25, 0.5, 0.75, 1].map((f) => <span key={f}>{fmt(total * f)}</span>)}
            </div>
            <p className="mt-1 text-xs text-neutral-500">Grey: wide shot · Blue: punch-in. Hover a part for its times.</p>
            {warnings.map((w) => <p key={w} className="mt-1 text-xs text-amber-300">⚠ {w}</p>)}
          </div>

          {/* Creative director: the message it heard and every cut it made, so nothing disappears silently. */}
          {(plan.message || plan.removed?.length > 0) && (
            <details className="mt-6 rounded-lg border border-neutral-800 px-4 py-3 text-sm" open>
              <summary className="cursor-pointer font-medium">
                What the director cut ({plan.removed.length})
              </summary>
              {plan.message && <p className="mt-2 text-neutral-300">Message: {plan.message}</p>}
              <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto">
                {plan.removed.map((r, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="w-14 shrink-0 tabular-nums text-neutral-500">{fmt(r.start)}</span>
                    <span className="w-24 shrink-0 text-neutral-400">{KIND_LABEL[r.kind] ?? r.kind}</span>
                    <span className="text-neutral-300 line-through decoration-red-400/70">{r.text}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-neutral-500">Times are from your original video. Say &quot;keep the ums&quot; in the chat to put them all back.</p>
            </details>
          )}

          {/* Timeline chat */}
          <div className="mt-6 rounded-lg border border-neutral-800">
            <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-2 text-sm">
              <span className="font-medium">Editor chat</span>
              <span className="text-xs text-neutral-500">
                {mode === "claude" ? "Claude editor" : mode === "rules" ? "Free mode (add an API key for Claude)" : ""}
                {history.length > 0 && (
                  <button onClick={undo} disabled={busy} className="ml-3 underline disabled:opacity-50">Undo</button>
                )}
              </span>
            </div>
            <div className="max-h-72 space-y-2 overflow-y-auto px-4 py-3 text-sm">
              {messages.map((m, i) => (
                <div key={i} className={m.from === "you" ? "text-right" : ""}>
                  <span className={`inline-block max-w-[85%] rounded-lg px-3 py-2 ${m.from === "you" ? "bg-white text-black" : "bg-neutral-800"}`}>
                    {m.text}
                  </span>
                </div>
              ))}
              {busy && !job && <p className="text-neutral-500">…</p>}
              <div ref={chatEnd} />
            </div>
            <form className="flex gap-2 border-t border-neutral-800 p-3"
              onSubmit={(e) => { e.preventDefault(); chat(); }}>
              <input value={draft} onChange={(e) => setDraft(e.target.value)} disabled={busy}
                placeholder='e.g. "cut 0:12 to 0:18", "zoom in from 30 to 35", "remove the ums"'
                className="flex-1 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-500" />
              <button type="submit" disabled={busy || !draft.trim()}
                className="rounded-md border border-neutral-600 px-4 py-2 text-sm hover:bg-neutral-800 disabled:opacity-50">Send</button>
            </form>
          </div>

          <button onClick={render} disabled={busy}
            className="mt-5 rounded-md bg-white px-5 py-2.5 text-sm font-medium text-black hover:bg-neutral-200 disabled:opacity-50">
            Render video
          </button>
        </>
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
          <video key={job.output} src={exportUrl(job)} controls className="max-h-[70vh] w-full rounded-lg bg-black" />
          <a href={exportUrl(job)} download className="mt-3 inline-block rounded-md bg-white px-4 py-2 text-sm font-medium text-black">
            Download MP4
          </a>
          <p className="mt-2 text-xs text-neutral-500">Use the player&apos;s time to tell the editor what to change, then render again. Only changed parts are re-rendered.</p>
        </div>
      )}
    </section>
  );
}
