# FRAMEWORK AI

An AI video editor for people who don't edit: upload raw footage, pick a style, get a professionally edited video back.

Products, in build order:
1. **Talking-head editor** (v0.1, in progress)
2. Real estate studio (photos and clips to a property tour)
3. Church media studio (sermon highlights, scripture overlays)

The AI decides the edit as a validated JSON plan. FFmpeg does the actual cutting and rendering, the same way every time. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

| Tool | Version | Check |
|---|---|---|
| Python | 3.11 or newer | `python --version` |
| Node.js | 20 or newer | `node --version` |
| FFmpeg (includes ffprobe) | 6 or newer | `ffmpeg -version` |
| Git | any | `git --version` |

Installing FFmpeg:
- **Windows:** `winget install Gyan.FFmpeg`, then open a new terminal.
- **macOS:** `brew install ffmpeg`
- **Ubuntu:** `sudo apt install ffmpeg`

## Run it locally

Backend (terminal 1):

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/api/health. You should see `"ffprobe": true, "ffmpeg": true`. If either is `false`, FFmpeg isn't on your PATH.

Frontend (terminal 2):

```bash
cd frontend
npm install
cp .env.example .env.local  # Windows: copy .env.example .env.local
npm run dev
```

Open http://localhost:3000 and drop in a video. You'll see its duration, resolution, frame rate, codecs and colour tags. Then use **Auto edit**: pick a format, click **Preview plan** to see what will be cut, and **Edit my video** to render. The finished MP4 plays on the page and can be downloaded.

Then type changes into the **Editor chat**, for example "cut 0:12 to 0:18", "zoom in from 30 to 35", "make it 16:9" or "make it tighter", and render again. Without an API key the chat runs in a free mode that understands common phrasings. Add `ANTHROPIC_API_KEY=...` to `backend/.env` and restart the backend to use the Claude editor, which understands any wording.

Your files are stored in `backend/storage/<media id>/` (source, analysis, plans and exports).

API docs are generated automatically at http://localhost:8000/docs.

## API (v0.3)

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health` | Checks FFmpeg/FFprobe are installed |
| POST | `/api/media` | Upload and inspect a video |
| GET / DELETE | `/api/media/{id}` | Read or delete an import |
| POST | `/api/media/{id}/analyze` | Loudness and silence detection |
| POST | `/api/media/{id}/plan` | Get a validated edit plan (nothing rendered) |
| POST | `/api/media/{id}/render` | Render a plan in the background, returns a job |
| GET | `/api/jobs/{job_id}` | Job status and progress |
| POST | `/api/media/{id}/chat` | Plain-English instruction in, updated plan out |
| GET | `/api/media/{id}/exports/{file}` | Download the finished MP4 |

## Tests

```bash
cd backend
pytest -q
```

The tests generate their own small videos with FFmpeg, so you don't need sample files.

## Status

See [docs/ROADMAP.md](docs/ROADMAP.md).
