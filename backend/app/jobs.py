"""Minimal background jobs for v0.1: a thread pool plus a JSON status file per job.

Good enough for one machine. When we have real users this becomes Redis + RQ workers,
with the same job status shape so the frontend doesn't change.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

log = logging.getLogger("framework.jobs")

Status = Literal["queued", "running", "done", "failed"]


class Job(BaseModel):
    job_id: str
    media_id: str
    kind: str
    status: Status = "queued"
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    output: str | None = None  # filename inside the media folder
    created_at: float
    updated_at: float


class JobStore:
    def __init__(self, root: Path, workers: int = 1):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # One worker: renders are CPU-heavy and a laptop can't run several at once well.
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")

    def _path(self, job_id: str) -> Path:
        if len(job_id) != 32 or not all(c in "0123456789abcdef" for c in job_id):
            raise KeyError(job_id)
        return self.root / f"{job_id}.json"

    def save(self, job: Job) -> None:
        job.updated_at = time.time()
        with self._lock:
            tmp = self._path(job.job_id).with_suffix(".tmp")
            tmp.write_text(job.model_dump_json(indent=2))
            tmp.replace(self._path(job.job_id))

    def get(self, job_id: str) -> Job:
        path = self._path(job_id)
        if not path.is_file():
            raise KeyError(job_id)
        return Job(**json.loads(path.read_text()))

    def submit(self, media_id: str, kind: str, fn: Callable[[Job, Callable[[float, str], None]], str]) -> Job:
        now = time.time()
        job = Job(job_id=uuid.uuid4().hex, media_id=media_id, kind=kind, created_at=now, updated_at=now)
        self.save(job)

        def update(progress: float, message: str = "") -> None:
            job.progress = round(progress, 3)
            if message:
                job.message = message
            self.save(job)

        def run() -> None:
            job.status = "running"
            self.save(job)
            try:
                job.output = fn(job, update)
                job.status, job.progress, job.message = "done", 1.0, "Finished"
            except Exception as exc:  # report every failure to the user, never hang
                log.error("Job %s failed: %s\n%s", job.job_id, exc, traceback.format_exc())
                job.status, job.error = "failed", str(exc)
            self.save(job)

        self._pool.submit(run)
        return job
