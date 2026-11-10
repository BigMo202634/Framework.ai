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

Open http://localhost:3000 and drop in a video. You'll see its duration, resolution, frame rate, codecs and colour tags.

API docs are generated automatically at http://localhost:8000/docs.

## Tests

```bash
cd backend
pytest -q
```

The tests generate their own small videos with FFmpeg, so you don't need sample files.

## Status

See [docs/ROADMAP.md](docs/ROADMAP.md).
