# Roadmap

## Done
- [x] Milestone 1: project structure, FastAPI backend, Next.js frontend, video import + FFprobe inspection, tests
- [x] Milestone 2: audio analysis, adaptive silence detection, edit plan + validator, mock Editor Brain, FFmpeg renderer (trim, punch-ins, reframe to 9:16 / 16:9 / 1:1 / 4:5), background render jobs with progress, auto-edit UI
- [x] Timeline chat: plain-English instructions (cut, zoom, format, pacing, undo) become validated timeline commands. Free rule-based mode, Claude mode with an API key. Segment cache so re-renders only redo changed parts.

- [x] Creative director cuts: word-level transcription (faster-whisper, phrase by phrase so "um"s are written out), then cut fillers, stutters, false starts and lines said twice. Rhythmic repeats are kept. Claude director (with an API key) also trims off-message parts while protecting jokes, suspense, reactions and momentum. Every cut is listed in the app.

## Current
- [ ] Test the Claude director live on real footage once an API key is set

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
- Silence detection cuts on volume only, so breaths and background noise can count as speech.
- Whisper still hides some hesitations inside a drawn-out word ("theeee"); those can't be cut without cutting the word.
- The free rule director only removes mistakes (fillers, stutters, retakes, repeats). Judging what is off-message needs the Claude director.
- Transcription is English-only for now (Whisper supports more; it needs a language setting).
- One render at a time (single background worker).

## Known bugs
- None yet.
