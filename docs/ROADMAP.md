# Roadmap

## Done
- [x] Milestone 1: project structure, FastAPI backend, Next.js frontend, video import + FFprobe inspection, tests
- [x] Milestone 2: audio analysis, adaptive silence detection, edit plan + validator, mock Editor Brain, FFmpeg renderer (trim, punch-ins, reframe to 9:16 / 16:9 / 1:1 / 4:5), background render jobs with progress, auto-edit UI
- [x] Timeline chat: plain-English instructions (cut, zoom, format, pacing, undo) become validated timeline commands. Free rule-based mode, Claude mode with an API key. Segment cache so re-renders only redo changed parts.

## Current
- [ ] Milestone 3: transcription (faster-whisper locally, API optional), word timings

## Next
- [ ] Milestone 4: animated ASS captions with word highlighting
- [ ] Milestone 5: face-tracked reframing and smarter punch-ins (on key words, not every cut)
- [ ] Milestone 6: music bed with ducking under speech
- [ ] Milestone 7: Claude Editor Brain behind the provider adapter
- [ ] Milestone 8: QA checks (caption sync, meaning preserved, black frames, loudness)
- [ ] Emotion layer: tone of the words + voice energy drive music and SFX choice
- [ ] Style presets from the reference creator breakdown (caption style, colour looks, SFX)
- [ ] Motion graphics layer (Remotion overlays: floating cards, graphs, mock-ups)
- [ ] Log footage support: camera profile picker, conversion LUT + look LUT

## Known limitations
- Punch-ins centre slightly above the middle of the frame; face tracking comes later.
- Free chat mode understands a fixed set of phrasings; Claude mode understands anything but needs an API key.
- Silence detection cuts on volume only, so breaths and background noise can count as speech. Transcript-based cutting (milestone 3+) fixes this.
- One render at a time (single background worker).

## Known bugs
- None yet.
