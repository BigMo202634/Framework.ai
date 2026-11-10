# Architecture and decisions

## The core idea

```
upload -> inspect (ffprobe) -> transcribe -> analyse -> EDITOR BRAIN -> edit plan (JSON)
       -> validate plan -> render (FFmpeg) -> QA -> export
```

The Editor Brain (Claude, or a mock) never touches pixels. It writes an edit plan: exact source in/out points, timeline positions, captions, zooms, crops, audio and export settings. A deterministic validator checks the plan before FFmpeg renders it. If the AI is wrong, the validator catches it instead of producing a broken video.

## Decisions

| # | Decision | Why |
|---|---|---|
| 1 | Python + FastAPI backend | Best libraries for media and AI (faster-whisper, PySceneDetect, OpenTimelineIO, MediaPipe). |
| 2 | Next.js + TypeScript + Tailwind frontend | Standard, fast to build, deploys anywhere. |
| 3 | FFmpeg for all editing and rendering | Free, fast, deterministic, runs on any machine. |
| 4 | ASS/libass captions for v0.1 | Free, rendered inside FFmpeg, supports word highlighting and pop animations. Heavier motion graphics may move to Remotion later. |
| 5 | Edit plan is validated JSON (Pydantic) | Makes AI output checkable, testable and undoable. |
| 6 | Provider adapters for every AI service | Swap Claude / OpenAI / local models without touching the pipeline. Mock providers allow ₦0 development. |
| 7 | Local file storage behind one class | Swapped for Cloudflare R2 in production without touching callers. |
| 8 | One command layer for app, API and MCP | The same edit commands drive the UI, the REST API and an MCP server, so Claude can operate the timeline. |
| 9 | OpenTimelineIO export (planned) | Videographers can open the AI's edit in DaVinci Resolve or Premiere and finish it there. |
| 10 | Log footage: user picks camera profile, official conversion LUT, then a creative look LUT (planned) | Matches the DaVinci workflow; conversion is always technically correct. |
| 11 | Claude Opus 5.5 as the default Editor Brain | Strong at multi-step planning, half the price of Fable 5.2. Re-evaluate on the hardest jobs. |

## Security basics

- API keys only live in backend environment variables, never in frontend code.
- Media IDs are server-generated UUIDs; anything else is rejected so paths can't escape the storage folder.
- Uploads are size-limited while streaming and deleted if FFprobe can't read them.
