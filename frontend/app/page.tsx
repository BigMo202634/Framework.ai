// Landing page: the first thing a visitor sees. Explains the product and sends them to /editor.

import Link from "next/link";

const FEATURES = [
  { icon: "🎬", title: "A creative director, not a silence cutter", text: "It reads what you said, finds your message, and cuts the ums, stutters, false starts and lines you said twice. Jokes, suspense and moments that build momentum stay in." },
  { icon: "💬", title: "Talk to your timeline", text: "\"Cut 0:12 to 0:18.\" \"Make it tighter.\" \"Put the ums back.\" Say it in plain words and the edit changes." },
  { icon: "🎚️", title: "A real timeline when you want control", text: "Video, audio waveform and every spoken word laid out side by side. Drag edges to trim, split, delete, punch in, undo. The way you would in DaVinci." },
  { icon: "📱", title: "One video, every platform", text: "Reframe for Reels and TikTok (9:16), YouTube (16:9), square or feed (4:5) in one click. Adjust the framing per clip." },
  { icon: "🔍", title: "Punch-ins that hide jump cuts", text: "Every other cut zooms in slightly, so a cut-down take still feels deliberate and alive." },
  { icon: "🎯", title: "Frame-accurate sync", text: "Lips and voice stay locked at every cut. We test sync to within a few milliseconds before anything ships." },
];

const SOON = ["Animated captions", "Music & sound effects matched to your tone", "B-roll suggestions", "Log footage (S-Log, C-Log) with LUTs", "Export to DaVinci Resolve"];

const AUDIENCES = [
  { title: "Creators & coaches", text: "Talking-head videos for TikTok, Reels and YouTube, cut tight and on message.", live: true },
  { title: "Churches", text: "Sermon highlights and clips with scripture overlays, ready for the week's socials.", live: false },
  { title: "Real estate", text: "Turn listing photos into a walkthrough video that shows only what's really there.", live: false },
  { title: "Videographers", text: "Describe the edit you want and refine it on a pro timeline.", live: false },
];

const FAQ = [
  ["Do I need to know how to edit?", "No. Upload, and the first cut is done for you. The timeline is there when you want to adjust something yourself, and the chat is there when you'd rather just say it."],
  ["What happens to my video?", "Your video is processed on the FRAMEWORK server. Only the words you spoke (the transcript) are sent to the AI editor, never the video itself."],
  ["Which files work?", "MP4, MOV (including iPhone HEVC), MKV, WebM and MXF, up to 2 GB."],
  ["How does pricing work?", "You'll buy credits and spend them on AI edits, so you only pay for what you use. Payment with Paystack is coming soon."],
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-[#0d0f14] text-neutral-300">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-white/5 bg-[#0d0f14]/85 backdrop-blur">
        <nav className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 text-sm">
          <Link href="/" className="text-base font-semibold tracking-tight text-white">FRAMEWORK <span className="text-violet-400">AI</span></Link>
          <div className="hidden gap-5 md:flex">
            <a href="#how" className="hover:text-white">How it works</a>
            <a href="#features" className="hover:text-white">Features</a>
            <a href="#who" className="hover:text-white">Who it&apos;s for</a>
            <a href="#pricing" className="hover:text-white">Pricing</a>
            <a href="#faq" className="hover:text-white">FAQ</a>
          </div>
          <Link href="/editor" className="ml-auto rounded-lg bg-white px-4 py-2 font-medium text-black hover:bg-neutral-200">Start editing</Link>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-[500px] max-w-4xl rounded-full bg-violet-600/20 blur-3xl" />
        <div className="relative mx-auto max-w-6xl px-4 pb-16 pt-20 text-center md:pt-28">
          <p className="mx-auto inline-block rounded-full border border-violet-400/30 bg-violet-500/10 px-3 py-1 text-xs text-violet-200">AI video editor for people who don&apos;t edit</p>
          <h1 className="mx-auto mt-6 max-w-4xl text-4xl font-semibold leading-tight tracking-tight text-white md:text-6xl">
            Say it once. <span className="bg-gradient-to-r from-violet-300 to-sky-300 bg-clip-text text-transparent">We&apos;ll cut it like a pro.</span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-neutral-400">
            FRAMEWORK AI listens to your video, finds the message you&apos;re trying to pass, and removes the ums, retakes and dead air.
            Then you fine-tune it on a real timeline, or just tell it what to change.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link href="/editor" className="rounded-lg bg-violet-600 px-6 py-3 font-medium text-white shadow-lg shadow-violet-600/30 hover:bg-violet-500">Edit a video now</Link>
            <a href="#how" className="rounded-lg border border-white/15 px-6 py-3 font-medium text-white hover:bg-white/5">See how it works</a>
          </div>
          <EditorMock />
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="mx-auto max-w-6xl px-4 py-20">
        <h2 className="text-center text-3xl font-semibold text-white">From raw take to ready-to-post in three steps</h2>
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {[
            ["1", "Upload your video", "Straight from your phone or camera. Any length, vertical or horizontal."],
            ["2", "The director makes the first cut", "Silences, ums, stutters and retakes go. Your message stays, and every cut is listed so you can put anything back."],
            ["3", "Fine-tune and export", "Drag, split and punch in on the timeline, or ask in the chat. Export an MP4 for any platform."],
          ].map(([n, t, d]) => (
            <div key={n} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-violet-500/15 font-semibold text-violet-300">{n}</span>
              <h3 className="mt-4 text-lg font-medium text-white">{t}</h3>
              <p className="mt-2 text-sm leading-relaxed text-neutral-400">{d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section id="features" className="border-y border-white/5 bg-white/[0.015]">
        <div className="mx-auto max-w-6xl px-4 py-20">
          <h2 className="text-3xl font-semibold text-white">Everything a good editor does, without the learning curve</h2>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="rounded-2xl border border-white/10 bg-[#11141b] p-6">
                <div className="text-2xl">{f.icon}</div>
                <h3 className="mt-3 font-medium text-white">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-400">{f.text}</p>
              </div>
            ))}
          </div>
          <div className="mt-10 rounded-2xl border border-dashed border-white/10 p-6">
            <p className="text-sm font-medium text-white">Coming next</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {SOON.map((s) => <span key={s} className="rounded-full bg-white/5 px-3 py-1 text-xs text-neutral-300">{s}</span>)}
            </div>
          </div>
        </div>
      </section>

      {/* Who it's for */}
      <section id="who" className="mx-auto max-w-6xl px-4 py-20">
        <h2 className="text-3xl font-semibold text-white">Built for people with something to say</h2>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {AUDIENCES.map((a) => (
            <div key={a.title} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
              <span className={`text-[11px] font-medium ${a.live ? "text-emerald-300" : "text-neutral-500"}`}>{a.live ? "● Available now" : "○ Coming soon"}</span>
              <h3 className="mt-2 font-medium text-white">{a.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-neutral-400">{a.text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="border-y border-white/5 bg-white/[0.015]">
        <div className="mx-auto max-w-3xl px-4 py-20 text-center">
          <h2 className="text-3xl font-semibold text-white">Pay only for what you edit</h2>
          <p className="mt-4 text-neutral-400">
            Buy credits and spend them on AI edits. No subscription needed to get started.
            Trimming and splitting by hand on the timeline is always free.
          </p>
          <p className="mt-6 inline-block rounded-full bg-amber-400/10 px-4 py-1.5 text-sm text-amber-200">Credit packs with Paystack are coming soon</p>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="mx-auto max-w-3xl px-4 py-20">
        <h2 className="text-3xl font-semibold text-white">Questions</h2>
        <div className="mt-8 divide-y divide-white/10 rounded-2xl border border-white/10">
          {FAQ.map(([q, a]) => (
            <details key={q} className="group p-5">
              <summary className="flex cursor-pointer list-none items-center justify-between font-medium text-white">
                {q}<span className="text-neutral-500 transition group-open:rotate-45">+</span>
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-neutral-400">{a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* Final CTA */}
      <section className="mx-auto max-w-6xl px-4 pb-24">
        <div className="rounded-3xl border border-violet-400/20 bg-gradient-to-br from-violet-600/20 to-sky-500/10 p-10 text-center">
          <h2 className="text-3xl font-semibold text-white">Your next video, edited before your coffee cools</h2>
          <Link href="/editor" className="mt-6 inline-block rounded-lg bg-white px-6 py-3 font-medium text-black hover:bg-neutral-200">Start editing</Link>
        </div>
      </section>

      <footer className="border-t border-white/5">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-8 text-xs text-neutral-500">
          <span>© 2026 FRAMEWORK AI</span>
          <span className="ml-auto">Made in Lagos</span>
        </div>
      </footer>
    </div>
  );
}

/** A drawn (not screenshot) picture of the editor, so the hero shows the product without loading media. */
function EditorMock() {
  const clips = [8, 5, 11, 4, 9, 6, 12, 5, 7, 10, 6, 8];
  return (
    <div className="mx-auto mt-14 max-w-5xl overflow-hidden rounded-2xl border border-white/10 bg-[#111319] text-left shadow-2xl shadow-black/60">
      <div className="flex h-8 items-center gap-1.5 border-b border-white/10 px-3">
        <span className="h-2.5 w-2.5 rounded-full bg-red-400/70" /><span className="h-2.5 w-2.5 rounded-full bg-amber-400/70" /><span className="h-2.5 w-2.5 rounded-full bg-emerald-400/70" />
        <span className="ml-3 text-[11px] text-neutral-500">FRAMEWORK AI · my-video.mov</span>
      </div>
      <div className="grid grid-cols-[1fr_2fr_1.3fr] gap-px bg-white/5 text-[11px]">
        <div className="bg-[#111319] p-3">
          <p className="font-medium text-neutral-300">Director cuts (31)</p>
          {["um,", "Hello.", "you know,", "I knew,", "uh,"].map((w, i) => (
            <p key={i} className="mt-2 rounded bg-white/[0.03] px-2 py-1 text-neutral-500"><span className="line-through decoration-red-400/70">{w}</span></p>
          ))}
        </div>
        <div className="flex items-center justify-center bg-black/50 p-4">
          <div className="relative aspect-[9/16] h-48 overflow-hidden rounded bg-gradient-to-b from-neutral-700 to-neutral-900">
            <div className="absolute bottom-0 left-1/2 h-28 w-24 -translate-x-1/2 rounded-t-full bg-neutral-500/60" />
            <div className="absolute left-1/2 top-10 h-12 w-12 -translate-x-1/2 rounded-full bg-neutral-400/70" />
            <span className="absolute right-1 top-1 rounded bg-sky-500/90 px-1 text-[8px] font-semibold text-black">PUNCH-IN</span>
          </div>
        </div>
        <div className="space-y-2 bg-[#111319] p-3">
          <p className="font-medium text-neutral-300">Editor chat</p>
          <p className="ml-auto w-fit rounded-lg bg-violet-600 px-2 py-1 text-white">make it tighter</p>
          <p className="w-fit rounded-lg bg-white/5 px-2 py-1">Re-cut the pacing: 58 parts, 3:21 long.</p>
        </div>
      </div>
      <div className="space-y-1 border-t border-white/10 bg-[#14161c] p-2">
        {["V1", "A1"].map((t) => (
          <div key={t} className="flex h-7 items-center gap-1">
            <span className="w-8 text-[10px] text-neutral-500">{t}</span>
            {clips.map((w, i) => (
              <span key={i} className={`h-full rounded-sm ${t === "A1" ? "bg-emerald-800/80" : i % 2 ? "bg-sky-700/90" : "bg-indigo-800/90"}`} style={{ flexGrow: w }} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
